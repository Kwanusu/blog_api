"""
Data migration (review fix A2): publish every post that existed before drafts were enforced.

Until now ``is_published`` was ignored by the API and defaulted to ``False``, so each existing post was
in fact visible to everybody. Enforcing the flag without this step would suddenly hide the whole blog.
New posts default to published (see the model); drafts are created explicitly with is_published=false.
"""
from django.db import migrations


def publish_all(apps, schema_editor):
    Blog = apps.get_model('blogs', 'Blog')
    Blog.objects.filter(is_published=False).update(is_published=True)


class Migration(migrations.Migration):

    dependencies = [
        ('blogs', '0006_bigautofield_drafts_ordering_index'),
    ]

    operations = [
        # Not reversible in a meaningful way (we cannot know which posts used to be drafts).
        migrations.RunPython(publish_all, migrations.RunPython.noop),
    ]
