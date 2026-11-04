import unittest

from orchestrator.state_machine import TERMINAL, TRANSITIONS, InvalidTransition, validate_transition
from orchestrator.state_machine import SagaState as S
from orchestrator.workflow import compensation_plan
from shared.messages import Envelope, SchemaError
from shared.retry import RetryPolicy, is_retryable_code
from shared.timeutil import FakeClock


class StateMachineTests(unittest.TestCase):
    def test_valid_transitions(self):
        for a, b in [(S.PENDING, S.RUNNING), (S.RUNNING, S.COMPLETED), (S.RUNNING, S.COMPENSATING),
                     (S.COMPENSATING, S.COMPENSATED), (S.COMPENSATING, S.REQUIRES_ATTENTION),
                     (S.REQUIRES_ATTENTION, S.RUNNING), (S.REQUIRES_ATTENTION, S.COMPENSATING)]:
            validate_transition(a, b)

    def test_invalid_transitions_rejected(self):
        for a, b in [(S.COMPLETED, S.RUNNING), (S.COMPENSATED, S.COMPLETED), (S.PENDING, S.COMPLETED),
                     (S.RUNNING, S.COMPENSATED), (S.FAILED, S.RUNNING), (S.COMPENSATING, S.COMPLETED)]:
            with self.assertRaises(InvalidTransition):
                validate_transition(a, b)

    def test_terminal_states_have_no_exits(self):
        for t in TERMINAL:
            self.assertEqual(TRANSITIONS[t], set())


class CompensationRuleTests(unittest.TestCase):
    def test_reverse_order_and_only_completed(self):
        plan = compensation_plan({"RESERVE_INVENTORY": "COMPLETED", "PROCESS_PAYMENT": "COMPLETED", "ARRANGE_SHIPPING": "FAILED"})
        self.assertEqual(plan, ["PROCESS_PAYMENT", "RESERVE_INVENTORY"])

    def test_failed_payment_is_never_compensated(self):
        plan = compensation_plan({"RESERVE_INVENTORY": "COMPLETED", "PROCESS_PAYMENT": "FAILED", "ARRANGE_SHIPPING": "PENDING"})
        self.assertEqual(plan, ["RESERVE_INVENTORY"])

    def test_unknown_outcome_not_compensated_blindly(self):
        self.assertEqual(
            compensation_plan({"RESERVE_INVENTORY": "COMPLETED", "PROCESS_PAYMENT": "UNKNOWN"}),
            ["RESERVE_INVENTORY"],
        )


class RetryTests(unittest.TestCase):
    def test_exponential_backoff_capped(self):
        p = RetryPolicy(max_attempts=5, base_delay_s=1, factor=2, max_delay_s=5)
        self.assertEqual([p.delay(i) for i in (1, 2, 3, 4)], [1, 2, 4, 5])

    def test_should_retry_bounded_and_classified(self):
        p = RetryPolicy(max_attempts=3)
        self.assertTrue(p.should_retry(1, True))
        self.assertFalse(p.should_retry(3, True))
        self.assertFalse(p.should_retry(1, False))
        self.assertTrue(is_retryable_code("TIMEOUT"))
        self.assertFalse(is_retryable_code("PAYMENT_DECLINED"))


class SchemaTests(unittest.TestCase):
    def good(self, **over):
        d = {"message_id": "m1", "type": "payment.authorize", "version": 1, "saga_id": "s", "correlation_id": "c",
             "idempotency_key": "k", "payload": {"order_id": "o", "step": "PROCESS_PAYMENT", "action": "forward", "attempt": 1}}
        d.update(over)
        return d

    def test_roundtrip(self):
        import json
        env = Envelope.from_json(json.dumps(self.good()))
        self.assertEqual(Envelope.from_json(env.to_json()).message_id, "m1")

    def test_rejects_bad_messages(self):
        import json
        for bad in ["not json", json.dumps([1]), json.dumps(self.good(version=2)), json.dumps(self.good(type="x.y")),
                    json.dumps({k: v for k, v in self.good().items() if k != "saga_id"}),
                    json.dumps(self.good(payload={"order_id": "o"})),
                    json.dumps(self.good(
                        type="inventory.reserve",
                        payload={"order_id": "o", "step": "s", "action": "forward", "attempt": 1,
                                 "items": [{"sku": "A", "quantity": 0}]},
                    ))]:
            with self.assertRaises(SchemaError):
                Envelope.from_json(bad)


class ClockTests(unittest.TestCase):
    def test_fake_clock(self):
        c = FakeClock(); a = c.now_iso(); c.advance(5); self.assertLess(a, c.now_iso())


if __name__ == "__main__":
    unittest.main()
