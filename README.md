# Thesis_record

MPI communication–computation overlap experiments. Requires Python 3.10+. Start from the repository root.

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

**Access a remote server**

Run this in a separate terminal on your own computer, replacing `user@server` with your SSH login:

```bash
ssh -N -L 8000:127.0.0.1:8000 -L 8765:127.0.0.1:8765 user@server
```

Keep the tunnel open and visit the URLs above in your local browser. Run the two services in separate terminals; press `Ctrl+C` to stop each one.

See [comb_with_compute/README.md](comb_with_compute/README.md) for COMB build instructions.
