#!/bin/sh
# Start several development servers from one command.
#
# Each argument is one service, written as `label=command`. The script starts every command,
# prefixes each output line with the label, and keeps the services together: Ctrl-C stops all of
# them, and a service that exits on its own stops the others. No server stays behind to hold a
# port.
#
# Example:
#   scripts/run-dev.sh "api=uv run metis-api" "web=npm --prefix apps/web run dev"

set -u

# Job control puts each service in its own process group, so that one signal reaches a server and
# every process that it started. It also keeps the signals of the terminal for this script alone,
# which then stops the services in a known order.
set -m

if [ "$#" -eq 0 ]; then
	printf 'usage: %s label=command [label=command ...]\n' "$0" >&2
	exit 2
fi

pids=''
labels=''

# Stop every service that still runs. The traps are cleared first, so that a second Ctrl-C during
# the shutdown does not start this function again.
stop_services() {
	trap '' HUP INT TERM
	for pid in $pids; do
		kill -TERM "-$pid" 2>/dev/null
	done
	wait 2>/dev/null
}

# HUP comes when the terminal closes. The services are not in the process group of the terminal,
# so they do not get it themselves.
trap 'stop_services; exit 0' HUP INT TERM

for service in "$@"; do
	case $service in
	*=*) ;;
	*)
		printf '%s: expected label=command, got "%s"\n' "$0" "$service" >&2
		exit 2
		;;
	esac
	label=${service%%=*}
	cmd=${service#*=}
	# The command keeps its own stderr in the stream, so that a failure to start is as visible as
	# normal output. awk flushes every line; otherwise the prefixed output would sit in a buffer
	# while the server waits for requests. Stdin is empty: a service in a background process group
	# that reads the terminal is stopped by the kernel, and Vite reads it for its key shortcuts.
	(
		sh -c "$cmd" </dev/null 2>&1 |
			awk -v label="$label" '{printf "%s | %s\n", label, $0; fflush()}'
	) &
	pids="$pids $!"
	labels="$labels $label"
done

# Watch the services. `wait -n` would be the direct way to block until the first one ends. It is
# absent from the bash 3.2 that macOS supplies, so the loop asks each process instead. A server
# that ends while the others run has failed, whatever its exit code, so the script reports the
# label and exits 1.
#
# The pause runs in the background, and the script waits for it. With job control, a foreground
# command gets its own process group and the terminal, so Ctrl-C would stop only the pause and the
# loop would go on. `wait` also returns at once when a trapped signal comes.
while true; do
	set -- $pids
	for label in $labels; do
		pid=$1
		shift
		if ! kill -0 "$pid" 2>/dev/null; then
			printf '\n[run] %s stopped. Stopping the other servers.\n' "$label"
			stop_services
			exit 1
		fi
	done
	sleep 1 &
	wait "$!"
done
