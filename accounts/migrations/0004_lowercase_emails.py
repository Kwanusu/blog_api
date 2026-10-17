"""
Data migration (review fix B2): store every email address in lower case.

It must run *before* the case-insensitive unique constraint added in 0005. If two existing accounts
differ only by letter case the migration stops with a clear message instead of guessing which one to
keep: merge or rename one of them (for example in the admin) and run `migrate` again.
"""
from django.db import migrations
from django.db.models.functions import Lower


def lowercase_emails(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    lowered = {}
    for pk, email in User.objects.values_list('pk', 'email'):
        lowered.setdefault(email.lower(), []).append(pk)
    clashes = {email: pks for email, pks in lowered.items() if len(pks) > 1}
    if clashes:
        raise RuntimeError(
            'Cannot lower-case emails: these addresses exist more than once when letter case is '
            f'ignored: {sorted(clashes)}. Merge or change one account from each pair, then migrate again.'
        )
    User.objects.exclude(email=Lower('email')).update(email=Lower('email'))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_alter_user_managers_remove_user_username_and_more'),
    ]

    operations = [
        # Reverse is a no-op: the original capitalisation is not recoverable and is not needed.
        migrations.RunPython(lowercase_emails, migrations.RunPython.noop),
    ]
