import numpy as np
import tensorflow as tf
from OrnsteinNoise import OUActionNoise
from tensorflow.keras.models import clone_model
import time
from scipy.special import softmax
from utils import Plotter


class Step:  # Stores a step
    def __init__(self, state, action_continuous, action_discrete, reward, next_state, done):
        self.state = state
        self.action_continuous = action_continuous
        self.action_discrete = action_discrete
        self.reward = reward
        self.next_state = next_state
        self.done = done



class Worker:
    def __init__(self, name, global_network_P, global_network_dqn, global_optimizer_P, global_optimizer_dqn,
                 global_counter, env, max_global_steps, returns_list, n_steps=10, gamma=0.99):
        self.name = name
        self.global_network_P = global_network_P
        self.global_network_dqn = global_network_dqn
        self.global_optimizer_P = global_optimizer_P
        self.global_optimizer_dqn = global_optimizer_dqn
        self.global_counter = global_counter
        self.env = env
        self.state = self.env.reset()
        self.max_global_steps = max_global_steps
        self.global_step = 0
        self.returns_list = returns_list
        self.n_steps = n_steps
        self.gamma = gamma
        self.noise = OUActionNoise(mu=np.zeros(env.continuous_action_space.shape[0]))
        self.n_discrete_actions = env.discrete_action_space.n
        self.start_time = time.time()

        self.local_param_model = clone_model(global_network_P)
        self.local_param_model.set_weights(global_network_P.get_weights())
        self.local_dqn_model = clone_model(global_network_dqn)
        self.local_dqn_model.set_weights(global_network_dqn.get_weights())

    def run(self, coord):
        try:
            while not coord.should_stop():
                # Collect some experience
                experience = self.run_n_steps()

                # Update the global networks using local gradients
                self.update_global_parameters(experience)

                # Stop once the max number of global steps has been reached
                if self.max_global_steps is not None and self.global_step >= self.max_global_steps:
                    coord.request_stop()
                    return f'worker {self.name}, step: {self.global_step}'
        except tf.errors.CancelledError:
            return f'worker {self.name} tf.errors.CancelledError'

    def choose_action(self, state, current_step, stop_step):
        state = state[np.newaxis, :]
        # get continuous action
        mu = self.local_param_model.predict(state)  # returns list of list so get 0 ith element later on
        noise = self.noise()
        mu_prime = mu + noise
        action_continuous = min(mu_prime, np.array([[0.999]]))  # cannot have a split above 1
        assert action_continuous.shape == (1, 1)  # need this shape to run through actor_DQN
        # TODO this will need to be generalised by adding self.n_continuous_actions

        # get discrete action
        predict_discrete = self.local_dqn_model.predict([state, action_continuous])
        action_discrete = self.eps_greedy_action(state, predict_discrete, current_step, stop_step)

        action_continuous = action_continuous[0]  # take it back to the correct shape
        return action_continuous, action_discrete

    def eps_greedy_action(self, state, predict_discrete, current_step, stop_step, max_prob=1, min_prob=0.1):
        explore_threshold = max(max_prob - current_step / stop_step * (max_prob - min_prob), min_prob)
        random = np.random.rand()


        if random < explore_threshold:
            #first rule out impossible actions
            if 0 in state:
                for i in range(state.size):
                    if state[0][i] == 0:
                        if i != state.size - 1:
                            predict_discrete[:, i] = 0
                        if i != 0:
                            predict_discrete[:, i-1] = 0

                # paper uses uniform distribution
            discrete_distribution = softmax(predict_discrete)[0]
            action_discrete = np.random.choice(self.n_discrete_actions, p=discrete_distribution)
        else:
            #first rule out impossible actions
            if 0 in state:
                for i in range(state.size):
                    if state[0][i] == 0:
                        if i != state.size - 1:
                            predict_discrete[i] = predict_discrete.min()  # can't be LK
                        if i != 0:
                            predict_discrete[i - 1] = predict_discrete.min()  # can't be HK (one lighter can't be LK)

            action_discrete = np.argmax(predict_discrete)
        return action_discrete

    def run_n_steps(self):
        experience = []
        score = 0
        for _ in range(self.n_steps):
            action = self.choose_action(self.state, self.global_step, self.max_global_steps/2)
            action_continuous, action_discrete = action
            next_state, reward, done, info = self.env.step(action)
            step = Step(self.state, action_continuous, action_discrete, reward, next_state, done)
            experience.append(step)
            score += reward
            self.state = next_state
            self.global_step = next(self.global_counter)
            if done:
                self.returns_list.append(score)
                print(f"Worker: {self.name} Score is {score}, global steps {self.global_step}/{self.max_global_steps}")
                self.state = self.env.reset()
                break

            if self.max_global_steps/20 % (self.global_step+1) == 0 and self.global_step > 100:
                print(f'global counter: {self.global_step}/{self.max_global_steps} \n')
                elapsed_time = time.time() - self.start_time
                remaining_time = elapsed_time * (self.max_global_steps - self.global_step) / max(self.global_step, 1)
                print(f'elapsed time: {elapsed_time / 60} min \n remaining time {remaining_time / 60} min \n')
                running_avg = np.mean(self.returns_list[-100:])
                print(f'running average is {running_avg}')
        return experience


    #@tf.function
    def update_global_parameters(self, experience):
        with tf.device('/CPU:0'):
            target = 0
            accumulated_param_gradients = 0
            accumulated_dqn_gradients = 0
            if not experience[-1].done:
                state = experience[-1].state[np.newaxis, :]
                action_continuous_predict = self.local_param_model.predict(state)
                target = np.max(self.local_dqn_model.predict([state, action_continuous_predict]))
            for step in reversed(experience):
                target = step.reward + self.gamma * target
                state = step.state[np.newaxis, :]

                with tf.GradientTape(persistent=True) as tape:
                    #param part
                    predict_param = self.local_param_model(state)
                    Qvalues = self.local_dqn_model([state, predict_param])
                    loss_param = - tf.reduce_sum(Qvalues)

                    #dqn part
                    target_dqn = Qvalues.numpy()
                    target_dqn[:, step.action_discrete] = target
                    target_dqn = tf.convert_to_tensor(target_dqn)
                    loss_dqn = tf.keras.losses.MSE(Qvalues, target_dqn)
                    # get gradients of loss with respect to the param_model weights
                gradient_param = tape.gradient(loss_param, self.local_param_model.trainable_weights)
                gradient_param = [tf.clip_by_norm(grad, 5) for grad in gradient_param]

                gradient_dqn = tape.gradient(loss_dqn, self.local_dqn_model.trainable_weights)
                gradient_dqn = [tf.clip_by_norm(grad, 5) for grad in gradient_dqn]

                if accumulated_param_gradients == 0:
                    accumulated_param_gradients = gradient_param
                    accumulated_dqn_gradients = gradient_dqn
                else:
                    accumulated_param_gradients = [tf.add(accumulated_param_gradients[i], gradient_param[i])
                                                   for i in range(len(gradient_param))]
                    accumulated_dqn_gradients = [tf.add(accumulated_dqn_gradients[i], gradient_dqn[i])
                                                   for i in range(len(gradient_dqn))]
            # update global nets
            self.global_optimizer_P.apply_gradients(zip(accumulated_param_gradients,
                                                        self.global_network_P.trainable_weights))
            self.global_optimizer_dqn.apply_gradients(zip(accumulated_dqn_gradients,
                                                        self.global_network_dqn.trainable_weights))
            # update local nets
            self.local_param_model.set_weights(self.global_network_P.get_weights())
            self.local_dqn_model.set_weights(self.global_network_dqn.get_weights())