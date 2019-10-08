from P_DQN_Agent import Agent
import numpy as np
from utils import Plotter
from DistillationSimulator import Simulator

env = Simulator()
agent = Agent(alpha=0.0001 , beta=0.001, n_discrete_actions=env.discrete_action_space.n,
              n_continuous_actions=env.continuous_action_space.shape[0], state_shape=env.observation_space.shape)
np.random.seed(0)
total_eps = 50000
total_eps_greedy = total_eps/2

# if there is a saved agent then uncomment below:
# agent.load_models()

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

    if i % (total_eps/20) == 0 and i > 100:
        env.render()
        plotter = Plotter(score_history, i)
        plotter.plot()

agent.save_models()

plotter = Plotter(score_history, i)
plotter.plot(save=True)
done = False
state = env.reset()
score = 0
while done is False: # run an episode
    print(state)
    action = agent.best_action(state)
    action_continuous, action_discrete = action
    state, reward, done, info = env.step(action)
    score += reward

print(score)
print(env.sep_order)
print(env.split_order)