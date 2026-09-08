PREFIX ?= /usr/local
CARGO ?= cargo

.PHONY: help build test run list-ports install uninstall clean ocaml-verify

help:
	@echo "make build        compile the Rust host CLI/TUI"
	@echo "make test         run Rust tests"
	@echo "make run PORT=... launch the Rust serial TUI"
	@echo "make list-ports   list serial devices"
	@echo "make install      install Rust binary, man page, and desktop entry"
	@echo "make ocaml-verify run the optional OCaml lifecycle verifier"

build:
	$(CARGO) build --release

test:
	$(CARGO) test --workspace

run: build
	@test -n "$(PORT)" || (echo "usage: make run PORT=/dev/cu.usbserial-0001" && exit 1)
	target/release/es32-top tui --port $(PORT) --baud $(or $(BAUD),115200)

list-ports: build
	target/release/es32-top --list-ports

install: build
	install -d $(DESTDIR)$(PREFIX)/bin $(DESTDIR)$(PREFIX)/share/man/man1 $(DESTDIR)$(PREFIX)/share/applications
	install -m 755 target/release/es32-top $(DESTDIR)$(PREFIX)/bin/es32-top
	install -m 644 man/es32-top.1 $(DESTDIR)$(PREFIX)/share/man/man1/es32-top.1
	install -m 644 share/applications/es32-top.desktop $(DESTDIR)$(PREFIX)/share/applications/es32-top.desktop

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/bin/es32-top
	rm -f $(DESTDIR)$(PREFIX)/share/man/man1/es32-top.1
	rm -f $(DESTDIR)$(PREFIX)/share/applications/es32-top.desktop

clean:
	cargo clean

ocaml-verify:
	@test -n "$(TRACE)" || (echo "usage: make ocaml-verify TRACE=transitions.txt" && exit 1)
	dune exec --root tools/ocaml ./esp_top_verify.exe -- $(TRACE)
