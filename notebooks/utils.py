from typing import Optional

import torch
from jaxtyping import Float

from toto.model.toto import Toto
from toto.model.util import KVCache

DEVICE = "cuda"

toto = None


def load_model():
    global toto
    toto = Toto.from_pretrained("Datadog/Toto-Open-Base-1.0").to(DEVICE)
    toto.eval()
    toto.use_memory_efficient = True
    toto.compile()


@torch.inference_mode()
def embed(inputs: Float[torch.Tensor, "batch variate time_steps"]) -> Float[torch.Tensor, "batch variates seq_len embed_dim"]:
    global toto
    if toto is None:
        load_model()

    if not isinstance(inputs, torch.Tensor):
        inputs = torch.tensor(inputs, device=DEVICE)

    if inputs.ndim < 3:
        inputs = inputs.unsqueeze(0)

    input_padding_mask, id_mask = torch.full_like(inputs, True, dtype=torch.bool), torch.zeros_like(inputs)

    kv_cache: Optional[KVCache] = None
    scaling_prefix_length: Optional[int] = None

    scaled_inputs: Float[torch.Tensor, "batch variate time_steps"]
    loc: Float[torch.Tensor, "batch variate time_steps"]
    scale: Float[torch.Tensor, "batch variate time_steps"]

    # Standard scaling operation, same API but without ID mask.
    scaled_inputs, loc, scale = toto.model.scaler(
        inputs,
        weights=torch.ones_like(inputs, device=inputs.device),
        padding_mask=input_padding_mask,
        prefix_length=scaling_prefix_length,
    )

    if kv_cache is not None:

        prefix_len = toto.model.patch_embed.stride * kv_cache.current_len(0)

        # Truncate inputs so that the transformer only processes
        # the last patch in the sequence. We'll use the KVCache
        # for the earlier patches.
        scaled_inputs = scaled_inputs[:, :, prefix_len:]

        # As a simplification, when using kv cache we only allow decoding
        # one step at a time after the initial forward pass.
        assert (prefix_len == 0) or (
            scaled_inputs.shape[-1] == toto.model.patch_embed.stride
        ), "Must decode one step at a time."

        input_padding_mask = input_padding_mask[:, :, prefix_len:]
        id_mask = id_mask[:, :, prefix_len:]

    embeddings: Float[torch.Tensor, "batch variate seq_len embed_dim"]
    reduced_id_mask: Float[torch.Tensor, "batch variate seq_len"]

    embeddings, reduced_id_mask = toto.model.patch_embed(scaled_inputs, id_mask)

    # Apply the transformer on the embeddings
    transformed: Float[torch.Tensor, "batch variates seq_len embed_dim"] = toto.model.transformer(
        embeddings, reduced_id_mask, kv_cache
    )
    return transformed.cpu()
