"""voz-rapida [--daemon | --toggle | --record | --quit]

  (sem argumentos)  igual a --daemon
  --daemon          inicia o app (ícone na bandeja / barra de menus)
  --toggle          começa ou para a gravação (inicia o app se preciso)
  --record          começa a gravar (não faz nada se já estiver gravando)
  --quit            encerra o app
"""

import sys


def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0
    if sys.platform == "darwin":
        from .macos import main as run
    elif sys.platform.startswith("linux"):
        from .linux import main as run
    else:
        sys.exit("Voz Rápida suporta Linux e macOS.")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
