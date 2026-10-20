# Thesis_record

MPI 通信与计算重叠实验记录。需要 Python 3.10+，以下命令从仓库根目录开始执行。

**查看 Dashboard（实验结果）**

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory comb_lab
```

浏览器打开 <http://127.0.0.1:8000/message-overlap-dashboard/>。已有结果可直接查看，无需重新运行实验。

**启动 Web 界面（配置、生成和管理实验）**

首次使用时创建环境并安装依赖：

```bash
cd comb_lab
python3 -m venv venv
venv/bin/python -m pip install click rich PyYAML Jinja2 numpy matplotlib
```

之后在 `comb_lab` 目录启动：

```bash
venv/bin/python mpi_lab.py gui --web --host 127.0.0.1 --port 8765
```

浏览器打开 <http://127.0.0.1:8765/>。生成或运行实验前，需准备编译好的 COMB 程序，并按所在集群修改 `config/comb_cm4.yaml` 中的路径、MPI 和 Slurm 配置。

**在远程服务器上运行时**

在自己电脑的新终端执行，将 `用户名@服务器` 替换为实际 SSH 登录地址：

```bash
ssh -N -L 8000:127.0.0.1:8000 -L 8765:127.0.0.1:8765 用户名@服务器
```

保持终端运行，再用本机浏览器打开上述地址。两个服务可分别在不同终端运行，按 `Ctrl+C` 停止。

COMB 源码与编译说明见 [comb_with_compute/README.md](comb_with_compute/README.md)。
