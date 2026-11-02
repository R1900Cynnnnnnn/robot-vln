"""Stop-only desktop panel for the robot web API.

The window never sends motion or releases an E-stop. It displays an E-stop as
confirmed only after the robot's safety node reports both the latch and zero
output. A network failure is displayed as an unknown state, not a successful
stop. Use a physical power cut for failures outside the software path.
"""

import argparse
import json
import math
import queue
import threading
import tkinter as tk
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def assess_state(state):
    """Return (message, color) based on an observed robot-side safety report."""
    safety = state.get('safety') or {}
    age = ((state.get('topics') or {}).get('safety') or {}).get('age')
    if not isinstance(age, (int, float)) or not math.isfinite(age) or age > 1.0:
        return '安全节点状态过期：无法确认停车', '#b91c1c'
    output = safety.get('out')
    if not isinstance(output, list) or len(output) != 3:
        return '缺少底盘输出回执：无法确认停车', '#b91c1c'
    try:
        output = [float(value) for value in output]
    except (TypeError, ValueError):
        return '底盘输出回执无效：无法确认停车', '#b91c1c'
    if any(not math.isfinite(value) or abs(value) > 0.001 for value in output):
        return '底盘仍有非零速度指令：立即现场断电', '#b91c1c'
    if state.get('estop') and safety.get('estop'):
        return '车端安全节点确认：软件停车已锁定', '#166534'
    return '软件停车未锁定；小车充电中请勿下发运动命令', '#b45309'


class RobotAPI:
    def __init__(self, host, port=8080, token='', timeout=0.75):
        self.base = f'http://{host}:{port}'
        self.query = '?' + urlencode({'token': token}) if token else ''
        self.timeout = timeout

    def state(self):
        with urlopen(self.base + '/api/state' + self.query, timeout=self.timeout) as response:
            return json.load(response)

    def stop(self):
        data = b'{"on":true}'
        request = Request(self.base + '/api/estop' + self.query, data=data,
                          headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=self.timeout) as response:
            result = json.load(response)
        if result.get('ok') is not True or result.get('estop') is not True:
            raise RuntimeError('车端没有确认急停请求')
        return result


class StopPanel:
    def __init__(self, root, api):
        self.root = root
        self.api = api
        self.results = queue.Queue()
        self.poll_busy = False
        self.stop_busy = False
        self.held = False

        root.title('机器人本机停车面板')
        root.geometry('520x290')
        root.minsize(480, 260)
        root.attributes('-topmost', True)
        root.configure(bg='#111827')

        tk.Label(root, text='车载软件停车', fg='white', bg='#111827',
                 font=('Microsoft YaHei UI', 20, 'bold')).pack(pady=(15, 3))
        tk.Label(root, text='点击按钮，或在本窗口按空格 / Esc', fg='#d1d5db',
                 bg='#111827', font=('Microsoft YaHei UI', 11)).pack()
        self.button = tk.Button(root, text='立即停车', command=self.stop,
                                bg='#dc2626', fg='white', activebackground='#991b1b',
                                font=('Microsoft YaHei UI', 32, 'bold'),
                                relief='flat', cursor='hand2')
        self.button.pack(fill='both', expand=True, padx=25, pady=16)
        self.message = tk.Label(root, text='正在读取车端状态…', fg='#fbbf24',
                                bg='#111827', font=('Microsoft YaHei UI', 11), wraplength=480)
        self.message.pack(pady=(0, 12))
        root.bind_all('<Escape>', self._key_stop)
        root.bind_all('<space>', self._key_stop)
        self._poll()
        self._drain()

    def _key_stop(self, event):
        self.stop()
        return 'break'

    def _work(self, kind, operation):
        try:
            self.results.put((kind, operation(), None))
        except (OSError, URLError, ValueError, RuntimeError) as error:
            self.results.put((kind, None, str(error)))

    def _poll(self):
        if not self.poll_busy:
            self.poll_busy = True
            threading.Thread(target=self._work, args=('state', self.api.state),
                             daemon=True).start()
        self.root.after(500, self._poll)

    def stop(self):
        self.held = True
        if self.stop_busy:
            return
        self.stop_busy = True
        self.message.configure(text='已发送停车请求，等待车端安全节点回执…', fg='#fbbf24')
        threading.Thread(target=self._work, args=('stop', self.api.stop), daemon=True).start()

    def _drain(self):
        try:
            while True:
                kind, value, error = self.results.get_nowait()
                if kind == 'stop':
                    self.stop_busy = False
                    if error:
                        self.message.configure(text=f'停车请求未送达或未确认：{error}；请现场断电',
                                               fg='#f87171')
                    else:
                        self.message.configure(text='车端已接收停车请求；正在核对安全节点…',
                                               fg='#fbbf24')
                else:
                    self.poll_busy = False
                    if error:
                        self.message.configure(text=f'车端连接中断：{error}；无法确认停车',
                                               fg='#f87171')
                    else:
                        message, color = assess_state(value)
                        self.message.configure(text=message, fg=color)
                        if self.held and not (value.get('estop') and
                                              (value.get('safety') or {}).get('estop')):
                            self.stop()
        except queue.Empty:
            pass
        self.root.after(100, self._drain)


def main():
    parser = argparse.ArgumentParser(description='Robot stop-only desktop panel')
    parser.add_argument('--host', default='192.168.43.18', help='onboard computer LAN address')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--token', default='', help='token only if the web service requires one')
    args = parser.parse_args()
    root = tk.Tk()
    StopPanel(root, RobotAPI(args.host, args.port, args.token))
    root.mainloop()


if __name__ == '__main__':
    main()
