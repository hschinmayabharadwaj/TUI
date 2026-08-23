PREFIX ?= /usr/local
PYTHON ?= python3

.PHONY: help venv install run list-ports man uninstall

help:
	@echo "make venv         create .venv and install Python deps"
	@echo "make run          launch the ESP32 monitor TUI"
	@echo "make list-ports   show serial ports"
	@echo "make install      install command, man page, and desktop entry"
	@echo "make uninstall    remove installed files"

venv:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e .

run:
	$(PYTHON) esp32_tui.py

list-ports:
	$(PYTHON) esp32_tui.py --list-ports

install:
	$(PYTHON) -m pip install .
	install -d $(DESTDIR)$(PREFIX)/share/man/man1
	install -d $(DESTDIR)$(PREFIX)/share/applications
	install -m 644 man/esp32-monitor.1 $(DESTDIR)$(PREFIX)/share/man/man1/esp32-monitor.1
	install -m 644 share/applications/esp32-monitor.desktop $(DESTDIR)$(PREFIX)/share/applications/esp32-monitor.desktop

uninstall:
	$(PYTHON) -m pip uninstall -y esp32-monitor || true
	rm -f $(DESTDIR)$(PREFIX)/share/man/man1/esp32-monitor.1
	rm -f $(DESTDIR)$(PREFIX)/share/applications/esp32-monitor.desktop
