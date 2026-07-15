::::: collapse Optimisation

### Optimisation

Everything is now in place: a shape described by numbers (section 2), a generator that turns numbers into meshes (section 3), and tests that turn meshes into a score (section 4).
Formally, we are looking for the parameter vector $\mathbf{x} \in \mathbb{R}^{24}$ (within the bounds of the Parameter Bounds tab) that maximizes the aggregated test score:

$$
\mathbf{x}^* = \arg\max_{\mathbf{x}} \; f(\mathbf{x})
$$

with $f$ evaluated by physics simulation. There is no formula for $f$, no gradient, and two evaluations of the same $\mathbf{x}$ can even give slightly different scores (contact simulation is noisy). This is a **black-box optimization** problem.

:::: collapse How CMA-ES searches
This lab uses **CMA-ES** (Covariance Matrix Adaptation Evolution Strategy), via the [Optuna](https://optuna.org) library.
CMA-ES maintains a multivariate Gaussian distribution over the parameter space. Each **generation**, it:

1. samples a few candidates from the distribution,
2. evaluates them (here: generate + simulate + score),
3. moves the mean of the Gaussian towards the best-scoring candidates and reshapes its covariance so that future samples concentrate along the directions that worked.

Over generations, the covariance even learns *correlations* between parameters: if a wide pincer only works together with a small tilt angle, the distribution stretches along that diagonal.

Why not something simpler? A **grid search** over 24 parameters with just 5 steps per axis would need $5^{24}$ evaluations — impossible. A **random search** never learns from its results. CMA-ES sits exactly in this lab's sweet spot: a few dozen continuous parameters, noisy evaluations, no gradient.

The first **10 trials** are sampled uniformly at random to seed the distribution before CMA-ES takes over, and candidates are evaluated **5 at a time in parallel** to make the most of your CPU.
::::

##### Running an optimization

In the **Optimise** tab, select the tests to include in the score and press **Run**. Then watch it live:

- **Progress** — the trials currently simulating, with their generation and state.
- **Performance** — the score history as it grows, the rolling average and best-so-far trends, and the **leaderboard** of the top designs with their preview images.

A full run is configured for up to 400 generations, but you do not need to wait for it: the run can be stopped at any time, and every finished trial is kept in `runtime/trials/` with its config, score and preview.

::: highlight
#icon("info-circle") **Note:**
Expect the early leaderboard to be full of failures and near-zero scores — with random seeding, most early shapes simply cannot grasp. Improvement typically appears once CMA-ES takes over and the average score starts to climb.
:::

##### Keeping what you find

When the leaderboard shows a design you like, its complete parameter set is in `runtime/trials/gen_XXXX/trial_XX/lab_config.jsonc`.
Copy it into `config/lab_config.jsonc` to make it the active gripper (and regenerate), or save it as a new numbered folder in `cool_grippers/` so it survives future runs.

:::: exercise
**Exercise 5:**

1. In the **Optimise** tab, select the *Grasp Hold* test and start a run. Let it work for 15–30 minutes.
2. While it runs, follow the **Progress** and **Performance** tabs. When does the best-so-far curve jump? Open the preview images of a bad and a good trial and compare their shapes.
3. Stop the run, take the best design from the leaderboard, make it the active config and generate it.
4. Watch it in the *Grasp Hold* scene (**Scenes** tab). Does it beat the reference gripper from Exercise 3? If it does, save it into `cool_grippers/` — you just designed a gripper without designing it.
::::

:::::
