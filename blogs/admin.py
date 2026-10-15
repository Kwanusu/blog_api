from django.contrib import admin

from .models import Author, Blog, Membership, MembershipPlan, Tip


@admin.register(Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'is_published', 'is_premium', 'created_at')
    list_filter = ('is_published', 'is_premium', 'created_at')
    search_fields = ('title', 'text')


admin.site.register(Author)


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'duration_days', 'is_active', 'sort_order')
    list_editable = ('price', 'is_active', 'sort_order')


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'starts_at', 'ends_at', 'created_at')
    list_filter = ('status', 'plan')
    search_fields = ('user__email',)
    readonly_fields = ('user', 'plan', 'payment', 'starts_at', 'ends_at', 'created_at')

    def has_add_permission(self, request):
        return False   # memberships come from payments, not from hand-entry


@admin.register(Tip)
class TipAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'blog', 'author', 'tipper', 'amount', 'status')
    list_filter = ('status', 'created_at')
    search_fields = ('blog__title', 'author__email', 'tipper__email', 'message')

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
