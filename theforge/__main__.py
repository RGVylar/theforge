"""Permite `python -m theforge ...` sin instalar el paquete."""

from theforge.cli import main

raise SystemExit(main())
