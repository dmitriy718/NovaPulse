"""Multi-channel notification system."""

from ha_agent.notifications.base import BaseNotifier, NotificationDispatcher
from ha_agent.notifications.slack import SlackNotifier
from ha_agent.notifications.email_notifier import EmailNotifier
from ha_agent.notifications.pagerduty import PagerDutyNotifier
from ha_agent.notifications.webhook import WebhookNotifier
from ha_agent.notifications.discord import DiscordNotifier

__all__ = [
    "BaseNotifier",
    "NotificationDispatcher",
    "SlackNotifier",
    "EmailNotifier",
    "PagerDutyNotifier",
    "WebhookNotifier",
    "DiscordNotifier",
]
