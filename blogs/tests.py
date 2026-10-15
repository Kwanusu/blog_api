import io
from unittest import mock

import cloudinary
from cloudinary import CloudinaryResource
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APITestCase

from accounts.models import User
from school.models import Course, Department

from .models import Author


def png_file(name='pic.png', size=(2, 2)):
    buf = io.BytesIO()
    Image.new('RGB', size, 'red').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


def fake_upload(file, **options):
    folder = options.get('folder', '')
    return CloudinaryResource(
        public_id=f'{folder}/fake', format='png', version='1',
        type='upload', resource_type='image',
    )


class CloudinaryImageTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin@x.com', 'pw-Strong-123', role=User.Role.ADMIN)
        cls.author = Author.objects.create(first_name='A', last_name='B', email='ab@x.com')
        cls.dept = Department.objects.create(name='Science')

    def setUp(self):
        cloudinary.config(cloud_name='demo', secure=True)
        self.client.force_authenticate(self.admin)
        patcher = mock.patch('cloudinary.models.uploader.upload_resource', side_effect=fake_upload)
        self.upload = patcher.start()
        self.addCleanup(patcher.stop)

    def test_blog_image_upload_returns_cloudinary_url(self):
        r = self.client.post('/api/v1/blogs/', {
            'title': 'T', 'text': 'x', 'author': self.author.id,
            'published_date': '2026-01-01', 'image': png_file(),
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.upload.call_args.kwargs['folder'], 'blogs')
        self.assertIn('res.cloudinary.com/demo/', r.data['image'])
        self.assertIn('blogs/fake', r.data['image'])

    def test_blog_without_image_still_works(self):
        r = self.client.post('/api/v1/blogs/', {
            'title': 'T', 'text': 'x', 'author': self.author.id,
            'published_date': '2026-01-01',
        })
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(r.data['image'])
        self.upload.assert_not_called()

    def test_course_thumbnail_upload(self):
        r = self.client.post('/api/courses/', {
            'name': 'Bio', 'code': 'B1', 'department': self.dept.id,
            'thumbnail': png_file(),
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.upload.call_args.kwargs['folder'], 'course_thumbnails')
        self.assertIn('course_thumbnails/fake', r.data['thumbnail'])
        self.assertIsNotNone(Course.objects.get(code='B1').thumbnail)

    def test_non_image_rejected(self):
        bad = SimpleUploadedFile('x.png', b'not an image', content_type='image/png')
        r = self.client.post('/api/courses/', {
            'name': 'Bio', 'code': 'B1', 'department': self.dept.id, 'thumbnail': bad,
        }, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.upload.assert_not_called()

    @override_settings(MAX_IMAGE_UPLOAD_SIZE=10)
    def test_oversized_image_rejected(self):
        r = self.client.post('/api/courses/', {
            'name': 'Bio', 'code': 'B1', 'department': self.dept.id, 'thumbnail': png_file(),
        }, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertIn('too large', str(r.data['thumbnail']))
