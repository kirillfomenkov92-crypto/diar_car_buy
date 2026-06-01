import py_compile, sys
files = [
    'main.py','config.py','database.py','analyzer.py',
    'notifier.py','bot_commands.py','speed_monitor.py',
    'parsers/avito.py','parsers/drom.py','parsers/youla.py',
    'parsers/autoru.py','parsers/avito_playwright.py',
    'parsers/vk_parser.py','parsers/tg_parser.py',
    'utils/headers.py','utils/retry_session.py','utils/cookie_extractor.py',
]
ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f'OK  {f}')
    except py_compile.PyCompileError as e:
        print(f'ERR {f}: {e}')
        ok = False
sys.exit(0 if ok else 1)
