from enum import Enum

from core.schemas.models import ChangeType, Plan
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
            raise TypeError("A política de autonomia exige uma instância de Plan.")

        if plan.risks:
            return AutonomyDecision.REQUIRE_HUMAN

        for change in plan.changes:
            if change.change_type == ChangeType.DELETE:
                return AutonomyDecision.REQUIRE_HUMAN

            self.security.validate_path(change.path)

            if change.change_type in (
                ChangeType.CREATE,
                ChangeType.MODIFY,
            ):
                if self.security.assess_content_risk(
                    change.content
                ) == "alto":
                    return AutonomyDecision.REQUIRE_HUMAN

        return AutonomyDecision.AUTO_APPROVE
