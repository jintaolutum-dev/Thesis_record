#!/bin/bash
# Source this file to activate the mpi_lab environment:
#   source ~/comb_lab/activate.sh

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
	echo "[mpi_lab] This script must be sourced, not executed."
	echo "[mpi_lab] Use: source ~/comb_lab/activate.sh"
	echo "[mpi_lab] Or run GUI directly: ./venv/bin/python mpi_lab.py gui --web"
	exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

module load python/3.10.12-extended 2>/dev/null || true
source "${SCRIPT_DIR}/venv/bin/activate"

export MPI_LAB_ROOT="${SCRIPT_DIR}"

# Quick launcher: start mpi_lab GUI from any directory.
# Usage:
#   mpi_gui                 # web mode on 127.0.0.1:8765
#   mpi_gui 0.0.0.0 8765    # custom host/port
#   mpi_gui_tk              # try tkinter GUI first (falls back to web in app)
mpi_gui() {
	local host="${1:-127.0.0.1}"
	local port="${2:-8765}"
	"${MPI_LAB_ROOT}/venv/bin/python" "${MPI_LAB_ROOT}/mpi_lab.py" gui --web --host "${host}" --port "${port}"
}

mpi_gui_stop() {
	local host="${1:-127.0.0.1}"
	local port="${2:-8765}"

	if pkill -f "mpi_lab.py gui --web --host ${host} --port ${port}" >/dev/null 2>&1; then
		echo "[mpi_lab] GUI stopped: http://${host}:${port}"
	else
		echo "[mpi_lab] GUI not running on http://${host}:${port}"
	fi
}

mpi_gui_restart() {
	local host="${1:-127.0.0.1}"
	local port="${2:-8765}"
	local log_file="${TMPDIR:-/tmp}/mpi_lab_${USER}_web_gui_${port}.log"

	mpi_gui_stop "${host}" "${port}" >/dev/null
	nohup "${MPI_LAB_ROOT}/venv/bin/python" "${MPI_LAB_ROOT}/mpi_lab.py" gui --web --host "${host}" --port "${port}" \
		>"${log_file}" 2>&1 &
	echo "[mpi_lab] GUI restarted: http://${host}:${port}"
	echo "[mpi_lab] GUI log: ${log_file}"
}

mpi_gui_tk() {
	"${MPI_LAB_ROOT}/venv/bin/python" "${MPI_LAB_ROOT}/mpi_lab.py" gui
}

# Auto-restart web GUI on activation (can be disabled via MPI_GUI_AUTO=0).
# Optional overrides before `source activate.sh`:
#   export MPI_GUI_HOST=127.0.0.1
#   export MPI_GUI_PORT=8765
#   export MPI_GUI_AUTO=0
_mpi_gui_auto_start() {
	local host="${MPI_GUI_HOST:-127.0.0.1}"
	local port="${MPI_GUI_PORT:-8765}"

	# Skip auto-start if explicitly disabled.
	if [[ "${MPI_GUI_AUTO:-1}" != "1" ]]; then
		return 0
	fi

	# Reload Python modules after source activation so the browser serves current code.
	mpi_gui_restart "${host}" "${port}"
}

_mpi_gui_auto_start

echo "[mpi_lab] Activated. Root: ${MPI_LAB_ROOT}"
echo "[mpi_lab] Usage: python \${MPI_LAB_ROOT}/mpi_lab.py --help"
echo "[mpi_lab] GUI: mpi_gui [host] [port]   (default: 127.0.0.1 8765)"
echo "[mpi_lab] GUI stop: mpi_gui_stop [host] [port]"
echo "[mpi_lab] GUI restart(bg): mpi_gui_restart [host] [port]"
echo "[mpi_lab] GUI(Tk): mpi_gui_tk"
