from app.models.fliggy import FliggyServiceStatus


class FliggyNotConfiguredError(RuntimeError):
    """飞猪门票查询功能未启用或尚未完成配置。"""


class DisabledFliggyTicketService:
    """默认关闭态，不执行任何外部网络请求。"""

    def status(self) -> FliggyServiceStatus:
        return FliggyServiceStatus(
            available=False,
            message="飞猪门票查询服务尚未配置",
        )

    def search_tickets(self, request):
        raise FliggyNotConfiguredError
