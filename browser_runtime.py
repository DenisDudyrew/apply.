"""Download the optional form browser once; normal API applications need no Chromium."""
import subprocess
import time


def launch_context(engine, path, ui=None, headless=True):
    options = {'headless': headless, 'viewport': {'width': 1280, 'height': 900}}
    try:
        return engine.chromium.launch_persistent_context(str(path), **options)
    except Exception as error:
        if "Executable doesn't exist" not in str(error):
            raise
    if ui:
        ui.progress(phase='preparing_browser', message='Разовая подготовка браузера для ручных форм. Требуется интернет.')
        ui.log('Подготавливаем браузер для анкет. Обычная отправка через API его не требует.')
    from playwright._impl._driver import compute_driver_executable
    node, cli = compute_driver_executable()
    process = subprocess.Popen([str(node), str(cli), 'install', 'chromium', '--only-shell'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 300
        while process.poll() is None:
            if ui:
                ui.check_stop()
            if time.monotonic() > deadline:
                raise RuntimeError('Подготовка браузера заняла слишком много времени. Проверьте интернет и попробуйте снова.')
            time.sleep(.2)
        if process.returncode != 0:
            raise RuntimeError('Не удалось установить браузер ручных форм. Проверьте интернет.')
    except BaseException:
        process.terminate()
        process.wait(timeout=10)
        raise
    return engine.chromium.launch_persistent_context(str(path), **options)
