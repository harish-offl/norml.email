from django.db import models


class Lead(models.Model):
    name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(unique=True)
    niche = models.CharField(max_length=100, blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    company = models.CharField(max_length=100, blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    last_status = models.CharField(max_length=20, default="pending")
    last_error = models.TextField(blank=True, default="")

    def __str__(self):
        return f"{self.name} ({self.email})"
