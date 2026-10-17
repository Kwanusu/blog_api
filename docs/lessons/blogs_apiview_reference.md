# Lesson reference: the original hand-written `APIView` blog API

This is how the blog endpoints were first written in the course, before they were replaced by the
`BlogViewSet` (a `ModelViewSet`) in `blogs/views.py`. It used to live as commented-out code at the bottom of that
file; it was moved here (review item C) so the production module stays clean while the lesson is preserved.

What to notice when you compare it with the `ModelViewSet`:

* every HTTP method is written by hand (`get`, `post`, `put`, `delete`);
* validation, saving, status codes and error handling are repeated in each method;
* there is no pagination, search, ordering or permission handling;
* a `ModelViewSet` plus a router gives list/create/retrieve/update/partial-update/destroy in a few lines.

```python
class BlogListCreateAPIView(APIView):
    def get(self, request):
        blogs = Blog.objects.select_related('author').all()
        serializer = BlogSerializer(blogs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = BlogSerializer(data=request.data)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            except IntegrityError:
                return Response({"detail": "Invalid data."}, status=status.HTTP_409_CONFLICT)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class BlogDetailAPIView(APIView):
    def get_object(self, pk):
        try:
            return Blog.objects.get(pk=pk)
        except Blog.DoesNotExist:
            raise exceptions.NotFound(f"Blog with ID {pk} not found.")

    def get(self, request, pk):
        blog = self.get_object(pk)
        serializer = BlogSerializer(blog)
        return Response(serializer.data)

    def put(self, request, pk):
        blog = self.get_object(pk)
        serializer = BlogSerializer(blog, data=request.data)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response(serializer.data)
            except IntegrityError:
                return Response({"detail": "Invalid data."}, status=status.HTTP_409_CONFLICT)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        blog = self.get_object(pk)
        blog.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class AuthorListAPIView(APIView):
    def get(self, request):
        authors = Author.objects.all()
        serializer = AuthorSerializer(authors, many=True)
        return Response(serializer.data)
```
