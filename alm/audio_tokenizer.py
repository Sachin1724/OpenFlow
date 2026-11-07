"""
audio_tokenizer.py — Neural Audio Codec Tokenizer for MIRA Audio Language Models
==============================================================================
Discretizes continuous 24,000 Hz speech waveforms into discrete RVQ codebook tokens
(and inverts discrete tokens back into broadcast-grade audio).

Powered by 24kHz Encodec (8 codebooks, 75 Hz frame rate, 1024 codebook entries).
"""

import os
import torch
import torchaudio
from encodec import EncodecModel
from encodec.utils import convert_audio
from typing import Tuple, Optional, Generator
import numpy as np

class AudioTokenizer:
    def __init__(self, target_bandwidth: float = 6.0, device: Optional[str] = None):
        """
        Initializes the 24kHz Discrete Neural Audio Codec.
        target_bandwidth: 6.0 kbps produces 8 codebooks with broadcast clarity.
        """
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.target_bandwidth = target_bandwidth
        
        self.model = EncodecModel.encodec_model_24khz()
        self.model.set_target_bandwidth(self.target_bandwidth)
        self.model = self.model.to(self.device).eval()
        
        self.sample_rate = self.model.sample_rate # 24,000 Hz
        self.channels = self.model.channels       # 1 (Mono)
        self.num_codebooks = 8                    # 8 RVQ layers at 6.0 kbps
        self.codebook_size = 1024                 # 1024 discrete tokens per codebook
        self.frame_rate = 75                      # 75 discrete frames per second

    @torch.inference_mode()
    def encode(self, wav: torch.Tensor, sr: int) -> torch.Tensor:
        """
        Encodes [channels, samples] or [batch, channels, samples] into discrete integer tokens.
        Returns: LongTensor of shape [batch, num_codebooks, num_frames]
        """
        if wav.dim() == 3:
            wav = wav.squeeze(0) # [C, T]
        elif wav.dim() == 1:
            wav = wav.unsqueeze(0) # [1, T]
            
        # Convert audio (resampling & channel reduction) safely on CPU
        wav = convert_audio(wav.cpu(), sr, self.sample_rate, self.channels)
        
        if wav.dim() == 2:
            wav = wav.unsqueeze(0) # [1, C, T]
            
        wav = wav.to(self.device, dtype=torch.float32)
        encoded_frames = self.model.encode(wav)
        # encoded_frames is list of (codes, scale)
        codes = torch.cat([f[0] for f in encoded_frames], dim=-1) # [B, K, T]
        return codes

    @torch.inference_mode()
    def encode_file(self, wav_path: str) -> torch.Tensor:
        """Loads a WAV file from disk and encodes into discrete tokens."""
        wav, sr = torchaudio.load(wav_path)
        return self.encode(wav, sr)

    @torch.inference_mode()
    def decode(self, codes: torch.Tensor) -> torch.Tensor:
        """
        Decodes discrete integer tokens [B, K, T] back into 24,000 Hz continuous waveform.
        Returns: [B, 1, samples]
        """
        codes = codes.to(self.device)
        if codes.dim() == 2:
            codes = codes.unsqueeze(0)
            
        # Wrap into encodec frame structure: [(codes, None)]
        frames = [(codes, None)]
        wav = self.model.decode(frames)
        return wav.clamp(-1.0, 1.0)

    @torch.inference_mode()
    def decode_to_file(self, codes: torch.Tensor, output_path: str):
        """Decodes tokens and writes 24kHz WAV file directly to disk."""
        wav = self.decode(codes)
        torchaudio.save(output_path, wav[0].cpu(), self.sample_rate)

    @torch.inference_mode()
    def stream_decode(self, token_generator: Generator[torch.Tensor, None, None], chunk_frames: int = 15) -> Generator[np.ndarray, None, None]:
        """
        Streams audio chunks as discrete tokens arrive (<200ms latency).
        15 frames = 200ms of audio.
        """
        buffer = []
        for token_chunk in token_generator:
            buffer.append(token_chunk)
            curr = torch.cat(buffer, dim=-1)
            if curr.shape[-1] >= chunk_frames:
                wav_chunk = self.decode(curr[:, :, :chunk_frames])
                buffer = [curr[:, :, chunk_frames:]]
                yield wav_chunk[0, 0].cpu().numpy()
                
        if buffer and buffer[0].shape[-1] > 0:
            wav_chunk = self.decode(buffer[0])
            yield wav_chunk[0, 0].cpu().numpy()


if __name__ == '__main__':
    tokenizer = AudioTokenizer()
    print(f"✅ AudioTokenizer ready: {tokenizer.num_codebooks} codebooks @ {tokenizer.frame_rate} fps, {tokenizer.sample_rate} Hz")
