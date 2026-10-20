# Thesis_record

MPI communication–computation overlap experiments. Requires Python 3.10+. Start from the repository root.

All experiment results are stored in [`comb_lab/generated/`](comb_lab/generated/).

**View the dashboard**

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory comb_lab
```

Open <http://127.0.0.1:8000/message-overlap-dashboard/> to browse saved results without rerunning experiments.

**Start the web interface**

Create the environment and install dependencies once:

```bash
cd comb_lab
python3 -m venv venv
venv/bin/python -m pip install click rich PyYAML Jinja2 numpy matplotlib
```

Then run from `comb_lab`:

```bash
venv/bin/python mpi_lab.py gui --web --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/> to configure and manage experiments. Before generating or running jobs, build COMB and update the paths, MPI settings, and Slurm settings in `config/comb_cm4.yaml` for your cluster.

