"""model_resize.py - resizes Chatterbox T3's text embedding/head for the extended Odia tokenizer.

Adapted from RASMUS/Chatterbox-Finnish's resize_and_load_t3_weights (same mean-init strategy for
new tokens): https://huggingface.co/RASMUS/Chatterbox-Finnish/blob/main/src/model.py
"""
import logging

logger = logging.getLogger("odia_finetune.model_resize")


def resize_and_load_t3_weights(new_model, pretrained_state_dict):
    """Loads pretrained T3 weights into a model with a bigger text vocab.
    New text-embedding/output-head rows are mean-initialized from existing tokens.
    """
    new_state = new_model.state_dict()
    emb_name = "text_emb.weight"
    head_name = "text_head.weight"

    for name, param in pretrained_state_dict.items():
        if name in (emb_name, head_name):
            continue
        if name in new_state and new_state[name].shape == param.shape:
            new_state[name].copy_(param)
        else:
            logger.warning(f"Layer skipped (shape mismatch): {name}")

    for name in (emb_name, head_name):
        old_w = pretrained_state_dict[name]
        old_n = old_w.shape[0]
        new_n = new_state[name].shape[0]
        new_state[name][:old_n, :].copy_(old_w)
        if new_n > old_n:
            mean_row = old_w.mean(dim=0)
            new_state[name][old_n:, :].copy_(mean_row.unsqueeze(0).expand(new_n - old_n, -1))
        logger.info(f"{name}: {old_n} -> {new_n} tokens ({new_n - old_n} mean-initialized)")

    new_model.load_state_dict(new_state)
    return new_model
