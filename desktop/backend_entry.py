"""PyInstaller entry. Public resources only; data paths are created per user."""
import argparse
import os
import sys
import threading


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.desktop:
        os.environ['APPLY_DESKTOP'] = '1'
    from app_paths import initialize
    initialize()
    if args.self_test:
        import json
        from app_paths import DATA_DIR, RESOURCE_DIR
        from server import create_app
        create_app()
        print(json.dumps({'ok': True, 'resources': (RESOURCE_DIR / 'frontend/dist/index.html').exists(),
                          'clean_config': not json.loads((DATA_DIR / 'config.json').read_text()).get('resume_id')}), flush=True)
        return
    import ui
    if args.desktop:
        def parent_messages():
            try:
                for line in sys.stdin:
                    if line.strip() == 'SHUTDOWN':
                        break
            finally:
                ui.stop_requested.set()
                ui.commands.put({'action': 'stop'})
                ui.shutdown_requested.set()
        threading.Thread(target=parent_messages, daemon=True).start()
    ui.main(port=args.port, open_browser=not args.no_open and not args.desktop)


if __name__ == '__main__':
    main()
