import py_compile
from pathlib import Path

files = sorted(Path('.').rglob('*.py'))
bad = []
for f in files:
    if '.git' in str(f):
        continue
    try:
        py_compile.compile(str(f), doraise=True)
    except Exception as e:
        bad.append(f'{f}: {e}')

if bad:
    for b in bad:
        print('ERROR:', b)
else:
    print(f'OK: all {len(files)} files syntax clean')
