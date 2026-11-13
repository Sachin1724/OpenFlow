"""
test_advanced_crm_features.py — Automated Unit Tests for the 5 Voice CRM Magic Moments
========================================================================================
Covers:
1. test_cocktail_party_separation: Overlap detection & multi-channel source masking.
2. test_order_state_machine_surgical_diffs: Modifications, additions, and rollbacks.
3. test_entity_clarification_loop: Sub-88% confidence phonetic disambiguation.
4. test_multilingual_lid_routing: Real-time code-switching across Odia, Hindi, and English.
5. test_acoustic_emotion_mirroring: Cadence and pitch dynamic adaptation.
"""

import pytest
import numpy as np
from openflow.engine.blind_source_separation import CocktailPartySeparator
from openflow.gateway.order_state_machine import OrderStateMachine
from openflow.gateway.entity_clarification import EntityClarificationLoop
from openflow.engine.acoustic_lid_router import AcousticLIDRouter
from openflow.engine.emotion_mirror import AcousticEmotionMirror


class TestBlindSourceSeparation:
    def test_single_speaker_clean(self):
        sr = 24000
        t = np.linspace(0, 1.0, sr)
        clean_audio = 0.3 * np.sin(2 * np.pi * 150 * t)
        sep = CocktailPartySeparator(sample_rate=sr)
        is_over, ratio, _ = sep.detect_overlapping_speakers(clean_audio)
        assert not is_over
        assert ratio < 0.22

    def test_source_separation_reconstruction(self):
        sr = 24000
        t = np.linspace(0, 1.5, int(sr * 1.5))
        # Synthesize multi-harmonic signals
        spk1 = sum((0.2 / h) * np.sin(2 * np.pi * h * 130 * t) for h in range(1, 6))
        spk2 = sum((0.2 / h) * np.sin(2 * np.pi * h * 240 * t) for h in range(1, 6))
        mix = spk1 + spk2

        sep = CocktailPartySeparator(sample_rate=sr)
        tracks = sep.separate_tracks(mix, num_sources=2, force_separation=True)
        assert len(tracks) == 2
        assert len(tracks[0]) == len(mix)
        assert len(tracks[1]) == len(mix)
        # Verify tracks are audible and normalized
        assert np.max(np.abs(tracks[0])) <= 0.90
        assert np.max(np.abs(tracks[1])) <= 0.90


class TestOrderStateMachine:
    def test_item_addition_and_summary(self):
        fsm = OrderStateMachine()
        res = fsm.process_turn("ଗୋଟେ ମିଡିୟମ ପେପରୋନି ପିଜା")
        assert len(res["diffs"]) == 1
        assert res["diffs"][0]["action"] == "add"
        assert res["diffs"][0]["target"] == "pepperoni_pizza"
        assert fsm.get_cart_summary()["grand_total"] == 280.0

    def test_mid_sentence_modification_and_diff(self):
        fsm = OrderStateMachine()
        fsm.process_turn("ଗୋଟେ ମିଡିୟମ ପେପରୋନି ପିଜା")
        fsm.process_turn("ଆଉ ଦୁଇଟା ଭେଜ୍ ସୁପ୍ରିମ୍ ପିଜା")

        # Mid-sentence modification: change pepperoni to large, add five diet cokes
        res = fsm.process_turn("Actually, can you change the pepperoni to large and add five diet cokes")
        diff_actions = [d["action"] for d in res["diffs"]]
        assert "modify" in diff_actions
        assert "add" in diff_actions

        cart = fsm.get_cart_summary()
        # Large Pepperoni (380) + 2 Veggie (480) + 5 Diet Cokes (200) = 1060
        assert cart["grand_total"] == 1060.0
        assert cart["total_items"] == 8

    def test_rollback_undo(self):
        fsm = OrderStateMachine()
        fsm.process_turn("ଗୋଟେ ଚିକେନ ବିରିୟାନୀ ପ୍ୟାକ୍ କର")
        assert fsm.get_cart_summary()["total_items"] == 1

        fsm.process_turn("ଆଉ ଗୋଟେ ମସାଲା ଦୋସା")
        assert fsm.get_cart_summary()["total_items"] == 2

        res_undo = fsm.process_turn("undo")
        assert res_undo["action"] == "rollback"
        assert fsm.get_cart_summary()["total_items"] == 1


class TestEntityClarificationLoop:
    def test_high_confidence_bypasses_clarification(self):
        loop = EntityClarificationLoop(confidence_threshold=0.88)
        needs_clar, prompt, ctx = loop.evaluate_entity("customer_name", "ସଚିନ ମଲ୍ଲିକ", 0.95)
        assert not needs_clar
        assert prompt is None

    def test_low_confidence_triggers_clarification(self):
        loop = EntityClarificationLoop(confidence_threshold=0.88)
        needs_clar, prompt, ctx = loop.evaluate_entity("customer_name", "ମଲ୍ଲିକ", 0.72)
        assert needs_clar
        assert prompt is not None
        assert "ମଲ୍ଲିକ" in prompt

    def test_spelling_loop_disambiguation(self):
        loop = EntityClarificationLoop(confidence_threshold=0.88)
        needs_clar, prompt, _ = loop.evaluate_entity("customer_name", "Shijia", 0.80)
        assert needs_clar
        assert "S-H-I-J-I-A" in prompt
        # Resolve with candidate choice
        success, val, _ = loop.resolve_clarification("S-H-I-J-I-A")
        assert success
        assert val == "S-H-I-J-I-A"


class TestAcousticLIDRouter:
    def test_code_switching_explicit_commands(self):
        router = AcousticLIDRouter(default_lang="or")
        lang, conf, _ = router.detect_language("Can you speak in English, please?")
        assert lang == "en"
        assert conf == 1.0

        lang, conf, _ = router.detect_language("हिंदी में बात करो भैया")
        assert lang == "hi"
        assert conf >= 0.95

    def test_script_based_detection(self):
        router = AcousticLIDRouter(default_lang="en")
        lang, conf, _ = router.detect_language("ଗୋଟେ ଚିକେନ ବିରିୟାନୀ ପ୍ୟାକ୍ କର")
        assert lang == "or"
        assert conf >= 0.80


class TestAcousticEmotionMirror:
    def test_rapid_speech_triggers_rush_mode(self):
        mirror = AcousticEmotionMirror(sample_rate=24000)
        sr = 24000
        t = np.linspace(0, 1.2, int(sr * 1.2))
        wave = 0.3 * np.sin(2 * np.pi * 180 * t)
        profile = mirror.analyze_caller_emotion(
            wave,
            transcript="Quick make it fast actually change pepperoni to large",
            language="en"
        )
        assert profile.mode == "rush_transactional"
        assert profile.speed_factor >= 1.18
        assert profile.temperature <= 0.40
        assert not profile.allow_fillers

    def test_slow_speech_triggers_warm_mode(self):
        mirror = AcousticEmotionMirror(sample_rate=24000)
        sr = 24000
        t = np.linspace(0, 4.5, int(sr * 4.5))
        wave = 0.25 * np.sin(2 * np.pi * 140 * t)
        profile = mirror.analyze_caller_emotion(
            wave,
            transcript="Umm... please take your time and tell me what pizzas you have",
            language="en"
        )
        assert profile.mode == "warm_relaxed"
        assert profile.speed_factor <= 0.98
        assert profile.temperature >= 0.70
        assert profile.allow_fillers
        assert len(profile.reassurance_marker) > 0

