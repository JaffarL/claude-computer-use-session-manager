#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

if [ -z "${VNC_JWT_KEY:-}" ]; then
    echo "VNC_JWT_KEY is required" >&2
    exit 1
fi

export DISPLAY=":${DISPLAY_NUM}"
mkdir -p "${HOME}/.config/openbox" "${HOME}/.mozilla" /tmp/runtime
printf '%s' "${VNC_JWT_KEY}" > /tmp/runtime/vnc-jwt-key
chmod 600 /tmp/runtime/vnc-jwt-key

Xvfb "${DISPLAY}" -screen 0 "${WIDTH}x${HEIGHT}x24" -ac -nolisten tcp &
xvfb_pid=$!

attempt=0
while [ ! -S "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; do
    attempt=$((attempt + 1))
    if [ "${attempt}" -gt 100 ]; then
        echo "Xvfb did not become ready" >&2
        exit 1
    fi
    sleep 0.1
done

dbus-launch --exit-with-session openbox-session &
openbox_pid=$!
sleep 1

xterm \
    -title "Computer Use Session ${SESSION_ID:-unknown}" \
    -geometry 92x26+24+24 \
    -e sh -c 'printf "Session: %s\n\nThis desktop is isolated in its own Docker container.\n" "${SESSION_ID:-unknown}"; exec sh' &
xterm_pid=$!

x11vnc \
    -display "${DISPLAY}" \
    -forever \
    -shared \
    -nopw \
    -localhost \
    -rfbport 5900 \
    -o /tmp/x11vnc.log &
x11vnc_pid=$!

websockify \
    --web /opt/novnc \
    --token-plugin JWTTokenApi \
    --token-source /tmp/runtime/vnc-jwt-key \
    6080 \
    > /tmp/websockify.log 2>&1 &
websockify_pid=$!

wait_for_port() {
    port="$1"
    attempts=0
    while ! nc -z 127.0.0.1 "${port}"; do
        attempts=$((attempts + 1))
        if [ "${attempts}" -gt 100 ]; then
            echo "port ${port} did not become ready" >&2
            exit 1
        fi
        sleep 0.1
    done
}

wait_for_port 5900
wait_for_port 6080

echo "sandbox ready: session=${SESSION_ID:-unknown} display=${DISPLAY}"

while :; do
    for pid in "${xvfb_pid}" "${openbox_pid}" "${xterm_pid}" "${x11vnc_pid}" "${websockify_pid}"; do
        if ! kill -0 "${pid}" 2>/dev/null; then
            echo "a required sandbox process exited: pid=${pid}" >&2
            exit 1
        fi
    done
    sleep 5
done
