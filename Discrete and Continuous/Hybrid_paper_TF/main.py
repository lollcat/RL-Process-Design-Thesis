import os
from Distillation_disc_cont import Simulator
import numpy as np
from PDQN_Agent import Agent
from utils import Plotter
import matplotlib.pyplot as plt


env = Simulator()
agent = Agent(alpha=0.0001, beta=0.00001, input_dims=env.observation_space.shape, tau=0.001,
              env=env, batch_size=32, layer1_size=64, layer2_size=32, layer3_size=32,
              n_discrete_actions=env.discrete_action_space.n, n_continuous_actions=1)
np.random.seed(0)
total_eps = 20000
total_eps_greedy = total_eps/2
# if there is a saved agent then uncomment below:
#agent.load_models()

score_history = []
for i in range(total_eps):
    state = env.reset()
    done = False
    score = 0
    while not done:
        action = agent.choose_action(state, i, total_eps_greedy)
        action_continuous, action_discrete = action  # TODO continuous action range is wrong
        new_state, reward, done, info = env.step(action)
        agent.remember(state, action_continuous, action_discrete, reward, new_state, int(done))
        agent.learn()
        score += reward
        state = new_state
        # env.render()

    score_history.append(score)
    if i % 100 == 0:
        print('episode ', i, 'score %.2f' % score,
          'trailing 100 games avg %.3f' % np.mean(score_history[-100:]))

    if i % 1000 == 0 and i > 10:
        env.render()
        agent.save_models()

    if i % (total_eps/10) == 0 and i > 100:
        plotter = Plotter(score_history, i)
        plotter.plot()

done = False
state = env.reset()
while done is False: # run an episode
    action = agent.best_action(state)
    action = action_continuous, action_discrete
    state, reward, done, info = env.step(action)

print(env.sep_order)
print(env.split_order)