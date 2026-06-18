"""Guard: every encoding declared in the spec must have a registered StreamWriter, so a
stream can never be declared with an encoding that crashes get_writer at record time."""
import adalog.core.spec as spec
from adalog.core.recorder.writers import get_writer


def test_every_declared_encoding_has_a_registered_writer():
    encodings = [v for k, v in vars(spec).items() if k.startswith("ENC_") and isinstance(v, str)]
    assert encodings, "no ENC_* encodings found in spec"
    missing = []
    for enc in encodings:
        try:
            get_writer(enc)
        except KeyError:
            missing.append(enc)
    assert not missing, f"encodings declared in spec with no writer: {missing}"
