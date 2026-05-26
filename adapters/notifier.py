import platform
import sys


class Notifier:
    def notify(self, title: str, message: str = "") -> None:
        try:
            from plyer import notification
            notification.notify(title=title, message=message, app_name="Tatkal Agent", timeout=10)
        except Exception:
            print(f"\n🔔 {title}: {message}")

    def alert(self, message: str) -> None:
        self._beep()
        print(f"\n⚡ {message}")

    def _beep(self) -> None:
        if platform.system() == "Windows":
            try:
                import winsound
                for _ in range(3):
                    winsound.Beep(1000, 300)
                return
            except Exception:
                pass
        print("\a")
        sys.stdout.flush()
