"""MANUAL, authorized adapter smoke test. Never imported by normal test discovery.

Starts only after Enter in its neutral window. No profiles, clicks or game access.
This validates the native adapter, NOT the physical L+R activation path.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from threading import Event
from time import monotonic_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from r6_rebuild.mouse_output import OutputGate


class BoundedTrial:
    SEQUENCE = ((1, 1),) * 5 + ((-1, -1),) * 5
    LIMIT_NS = 2_000_000_000

    def __init__(self, sink, *, safe, clock=monotonic_ns):
        self.gate = OutputGate(sink)
        self.safe, self.clock = safe, clock
        self.stopped = Event()
        self.started = None
        self.rows = []
        self.total = [0, 0]
        self.reason = None

    def start(self):
        if self.started is not None or self.stopped.is_set() or not self.safe():
            raise RuntimeError('Ensaio indisponível, já usado, ou janela/botões inseguros.')
        self.started = self.clock()
        self.gate.arm(self.gate.epoch)

    def stop(self, reason):
        self.stopped.set()
        self.gate.block()
        self.reason = self.reason or reason

    def step(self):
        if self.started is None or self.stopped.is_set():
            return False
        elapsed = self.clock() - self.started
        if elapsed >= self.LIMIT_NS or not self.safe():
            self.stop('deadline-or-unsafe-environment')
            return False
        index = len(self.rows)
        if index >= len(self.SEQUENCE):
            self.stop('completed')
            return False
        dx, dy = self.SEQUENCE[index]
        if any(self.total[i] + abs(v) > 10 for i, v in enumerate((dx, dy))):
            self.stop('budget')
            return False
        try:
            sent = self.gate.move(dx, dy)
        except Exception:
            self.stop('output-error')
            raise
        if not sent:
            self.stop('blocked')
            return False
        self.total[0] += abs(dx); self.total[1] += abs(dy)
        self.rows.append({'at_ns': elapsed, 'dx': dx, 'dy': dy})
        if len(self.rows) == len(self.SEQUENCE):
            self.stop('completed')
        return not self.stopped.is_set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if not args.authorized:
        parser.error('Requer autorização explícita do usuário e --authorized.')
    report = args.report.resolve()
    if ROOT not in report.parents or report.exists():
        parser.error('Use um relatório NOVO dentro do projeto.')
    import tkinter as tk
    from r6_rebuild.global_input import GlobalInput, WindowsHooks
    from r6_rebuild.mouse_output import WindowsMouseSink

    root = tk.Tk()
    root.title('R6-Rebuild — ENSAIO FÍSICO LIMITADO')
    root.geometry('680x250')
    native = WindowsHooks()
    listener = None
    trial = BoundedTrial(WindowsMouseSink(), safe=lambda:
        listener.operational and native._own_window() and not any(native.buttons_down()))
    def on_input(event):
        if event.kind == 'emergency':
            trial.stop('F12')
        elif event.kind == 'health' and not event.value:
            trial.stop('input-unavailable')
    listener = GlobalInput(on_input)
    message = tk.StringVar(value='Ensaio autorizado: até 2 segundos e 10 unidades por eixo.\n'
        'Nenhum clique será emitido. Mantenha L/R soltos. F12 interrompe.\n'
        'Enter inicia UMA VEZ; Escape encerra. Não use o jogo durante o ensaio.')
    tk.Label(root, textvariable=message, font=('Segoe UI', 12), pady=28).pack()
    def tick():
        try:
            again = trial.step()
        except Exception as exc:
            message.set(str(exc)); again = False
        if again:
            root.after(100, tick)  # no spin, no catch-up
        else:
            message.set(f'Ensaio encerrado: {trial.reason}.\n'
                        f'Chamadas: {len(trial.rows)}; total absoluto X/Y: {trial.total}.\n'
                        'Saída bloqueada. Escape encerra e salva o relatório.')
    def begin(event=None):
        if trial.started is not None or trial.stopped.is_set():
            return
        try:
            trial.start()
            message.set('Ensaio em andamento — F12 interrompe. Não pressione L/R.')
            tick()
        except Exception as exc:
            trial.stop('start-refused'); message.set(str(exc))
    root.bind('<Return>', begin)
    root.bind('<Escape>', lambda event: root.destroy())
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    try:
        listener.start()
        root.mainloop()
    finally:
        trial.stop('closed')
        listener.close()
        report.parent.mkdir(parents=True, exist_ok=True)
        data = {'at_utc': datetime.now(timezone.utc).isoformat(),
                'authorization': 'User explicitly authorized both requests on 2026-10-15.',
                'scope': 'Native adapter only, neutral foreground test window, no game or profiles.',
                'limits': {'duration_ns': trial.LIMIT_NS, 'absolute_per_axis': 10},
                'reason': trial.reason, 'movements': trial.rows, 'absolute_total': trial.total,
                'gate': trial.gate.snapshot(), 'listener_after_close': listener.snapshot(),
                'note': 'Units are SendInput relative units, not guaranteed screen pixels. OS scheduling is not hard realtime.'}
        with report.open('x', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
        print(json.dumps(data, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
