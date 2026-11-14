# GTK compatibility sources

These MIT-licensed upstream crates retain their individual licenses and ownership.
The GLib change exactly backports upstream commit b5a4071e439bef2b5eea76c3aa25e5ae84839e34.
The two macro manifests replace unmaintained proc-macro-error with the maintained
proc-macro-error3 3.1.1 with explicit syn2-error support under the same Rust import name. Each macro crate root adds
the absolute crate alias expected by maintained attribute expansions.
PROVENANCE.json records original archive checksums. Reproduce from an empty
third_party directory using desktop/scripts/vendor-gtk.py.
