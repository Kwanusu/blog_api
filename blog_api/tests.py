# """Project-level guard rails (code-review items A5 and B6)."""
# from io import StringIO

# from django.core.management import call_command
# from django.test import SimpleTestCase, override_settings


# class MigrationsAreInSyncTests(SimpleTestCase):
#     """
#     Fails when a model change was made without generating its migration. This is the check that would
#     have caught the AutoField/BigAutoField drift (review item A5); it is also run by the CI workflow.
#     """

#     databases = {'default'}   # makemigrations reads the migration history table

#     def test_no_model_changes_are_missing_a_migration(self):
#         out = StringIO()
#         try:
#             call_command('makemigrations', '--check', '--dry-run', stdout=out, stderr=out)
#         except SystemExit:
#             self.fail(f'Models have changes without a migration:\n{out.getvalue()}')

#     def test_every_app_uses_bigautofield(self):
#         from django.apps import apps
#         for config in apps.get_app_configs():
#             if config.name in ('accounts', 'blogs', 'school', 'payments', 'mpesa'):
#                 self.assertEqual(config.default_auto_field, 'django.db.models.BigAutoField', config.name)


# class ApiDocsTests(SimpleTestCase):
#     def test_the_openapi_schema_generates_without_errors(self):
#         from drf_spectacular.generators import SchemaGenerator
#         schema = SchemaGenerator().get_schema(request=None, public=True)
#         self.assertIn('/api/v1/blogs/', schema['paths'])
