# GTK compatibility sources

These MIT-licensed upstream crates retain their individual licenses and ownership.
The GLib change exactly backports upstream commit b5a4071e439bef2b5eea76c3aa25e5ae84839e34.
The two macro manifests replace unmaintained proc-macro-error with the maintained
proc-macro-error2 2.0.1 under the same Rust import name. No other source is changed.
PROVENANCE.json records original archive checksums. Reproduce from an empty
third_party directory using desktop/scripts/vendor-gtk.py.
