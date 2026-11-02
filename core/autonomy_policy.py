from enum import Enum

from core.schemas.models import Change, ChangeType, Plan
from core.security import SecurityPolicy


class AutonomyDecision(str, Enum):
    AUTO_APPROVE = "auto_approve"
    REQUIRE_HUMAN = "require_human"


class AutonomyPolicy:
    """Determina se um plano pode ser aprovado autonomamente."""

    def __init__(self, security=None):
        self.security = security or SecurityPolicy()

    def evaluate(self, plan: Plan) -> AutonomyDecision:
        if not isinstance(plan, Plan):
            raise TypeError(
                "A política de autonomia exige uma instância de Plan."
            )

        if not isinstance(plan.objective, str) or not plan.objective.strip():
            return AutonomyDecision.REQUIRE_HUMAN

        if not isinstance(plan.changes, list) or not plan.changes:
            return AutonomyDecision.REQUIRE_HUMAN

        if not isinstance(plan.tests, list):
            return AutonomyDecision.REQUIRE_HUMAN

        if not all(isinstance(item, str) for item in plan.tests):
            return AutonomyDecision.REQUIRE_HUMAN

        if not isinstance(plan.risks, list):
            return AutonomyDecision.REQUIRE_HUMAN

        if plan.risks:
            return AutonomyDecision.REQUIRE_HUMAN

        for change in plan.changes:
            if not isinstance(change, Change):
                return AutonomyDecision.REQUIRE_HUMAN

            if change.change_type not in (
                ChangeType.CREATE,
                ChangeType.MODIFY,
            ):
                return AutonomyDecision.REQUIRE_HUMAN

            if not isinstance(change.path, str) or not change.path.strip():
                return AutonomyDecision.REQUIRE_HUMAN

            if not isinstance(change.content, str):
                return AutonomyDecision.REQUIRE_HUMAN

            self.security.validate_path(change.path)

            if self.security.assess_content_risk(change.content) == "alto":
                return AutonomyDecision.REQUIRE_HUMAN

        return AutonomyDecision.AUTO_APPROVE
