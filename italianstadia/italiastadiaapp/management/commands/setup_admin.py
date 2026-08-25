import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Creates or updates a superuser from environment variables'

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')

        if not username or not password:
            self.stdout.write(self.style.WARNING('Superuser credentials missing in env variables.'))
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'is_superuser': True, 'is_staff': True}
        )

        user.set_password(password)
        # Explicitly ensure flags are correct if the user already existed
        user.is_superuser = True
        user.is_staff = True
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f'Successfully created superuser: {username}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Successfully updated superuser: {username}'))
    