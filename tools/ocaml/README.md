# Optional OCaml verifier

This tool is not part of the runtime. It checks lifecycle transition traces
against the same state machine implemented by the Rust host and C++ runtime.

Example trace:

    INSTALLED STARTING
    STARTING RUNNING
    RUNNING FAILED
    FAILED QUARANTINED

Run it with an OCaml/Dune installation:

    dune exec ./esp_top_verify.exe -- transitions.txt

OCaml is deliberately limited to this typed verification boundary. It does not
run on the ESP32 and does not duplicate the Rust CLI or terminal UI.
