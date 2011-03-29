from django.db import models
import datetime
from django.conf import settings
#from filefield_enhanced import RemovableFileField, RemovableImageField
#from helpers import pdf
from fields import ConstrainedImageField, AutoSlugField


__all__ = (
    'BaseContentModel',
    'BaseNamedModel',
    'DateAuditModel',
    'BaseSortedModel'
    'BaseContentModelWithImages',
    'BaseHierarchyModel',
)




def get_model_attr(instance, attr):
    for field in attr.split('__'):
        instance = getattr(instance, field)
    return instance



# used to implement prev() and next() methods in the base models classes below
def next_or_prev_in_order(instance, prev=False, qs=None):
    if not qs:
        qs = instance.__class__.objects
    if prev:
        qs = qs.reverse()
        lookup = 'lt'
    else:
        lookup = 'gt'
    
    q_list = []
    prev_fields = []
    if qs.model._meta.ordering:
        ordering = list(qs.model._meta.ordering)
    else:
        ordering = []
    
    for field in (ordering + ['pk',]):
        if field[0] == '-':
            this_lookup = (lookup == 'gt' and 'lt' or 'gt')
            field = field[1:]
        else:
            this_lookup = lookup
        q_kwargs = dict([(f, get_model_attr(instance, f)) for f in prev_fields])
        q_kwargs["%s__%s" % (field, this_lookup)] = get_model_attr(instance, field)
        q_list.append(models.Q(**q_kwargs))
        prev_fields.append(field)
    try:
        return qs.filter(reduce(models.Q.__or__, q_list))[0]
    except IndexError:
        return None



"""
Extend this class to get a record of when your model was created and last changed
"""
class DateAuditModel(models.Model):
    creation_date = models.DateTimeField(editable=False)
    last_updated = models.DateTimeField(editable=False)
    
    def get_creation_date_display(self):
        return self.creation_date.strftime("%Y-%m-%d %H:%M:%S")
    get_creation_date_display.admin_order_field = 'creation_date'
    get_creation_date_display.short_description = "Creation date"
    
    def get_last_updated_display(self):
        return self.last_updated.strftime("%Y-%m-%d %H:%M:%S")
    get_last_updated_display.admin_order_field = 'last_updated'
    get_last_updated_display.short_description = "Last updated"
    
    
    def prev(self):
        return next_or_prev_in_order(self, True, self.__class__.objects)
    def next(self):
        return next_or_prev_in_order(self, False, self.__class__.objects)
    
    
    class Meta:
        abstract = True
        ordering = ('-creation_date',)

def date_set(*args, **kwargs):
    if isinstance(kwargs['instance'], DateAuditModel):
        if not kwargs['instance'].creation_date:
            kwargs['instance'].creation_date = datetime.datetime.now()
        kwargs['instance'].last_updated = datetime.datetime.now()
models.signals.pre_save.connect(date_set)



class LiveManager(models.Manager):
    def get_query_set(self):
        return super(LiveManager, self).get_query_set().filter(is_live=True, publication_date__lte=datetime.datetime.now())
        
class FeaturedManager(LiveManager):
    def get_query_set(self):
        return super(FeaturedManager, self).get_query_set().filter(is_featured=True)
    def get_first(self):
        # gets first featured item, but falls back to first live item if none featured
        try:
            return self.get_query_set()[0]
        except IndexError:
            return super(FeaturedManager, self).get_query_set()[0]

class FeaturedManagerWithImages(FeaturedManager):
    def get_query_set(self):
        return super(FeaturedManagerWithImages, self).get_query_set().filter(image__isnull=False).distinct()
    

"""
Provides managers for 'live' and 'featured' instances, based on the is_live 
& publication_date fields, and the is_featured field respectively.
Also provides next/prev instance methods for all objects, just live and just
featured.
"""
class BaseContentModel(DateAuditModel):
    publication_date = models.DateField(default=datetime.date.today, db_index=True)#, help_text="This is the date from which the item will be shown on the site") # this field is required in order to use LiveManager
    is_live = models.BooleanField(default=getattr(settings, 'IS_LIVE_DEFAULT', 1), db_index=True, help_text="This must be ticked, and 'publication date' must be in the past, for the item to show on the site.")
    is_featured = models.BooleanField(default=0, db_index=True)
    
    objects = models.Manager()
    live = LiveManager()
    featured = FeaturedManager()
    
    class Meta(DateAuditModel.Meta):
        abstract = True
        ordering = ('-publication_date', '-creation_date',)

    def prev(self, qs=None):
        return next_or_prev_in_order(self, True, qs or self.__class__.objects)
    def next(self, qs=None):
        return next_or_prev_in_order(self, False, qs or self.__class__.objects)
    
    def prev_live(self):
        return next_or_prev_in_order(self, True, self.__class__.live)
    def next_live(self):
        return next_or_prev_in_order(self, False, self.__class__.live)

    def prev_featured(self):
        return next_or_prev_in_order(self, True, self.__class__.featured)
    def next_featured(self):
        return next_or_prev_in_order(self, False, self.__class__.featured)
    
    
def set_publication_date(sender, **kwargs):
    if not getattr(kwargs['instance'], 'publication_date', None):
        kwargs['instance'].publication_date = datetime.date.today()
models.signals.pre_save.connect(set_publication_date, sender=BaseContentModel)




"""
Provides name & auto-slug fields.
"""
class BaseNamedModel(models.Model):
    name = models.CharField(max_length=100)
    slug = AutoSlugField(populate_from="name")
       
    def __unicode__(self):
        return self.name
    
    class Meta:
        ordering = ('name',)
        abstract = True




class BaseSortedModel(models.Model):
    sort_order = models.IntegerField(default=0, blank=True)
        
    class Meta:
        abstract = True
        ordering = ('sort_order', 'id')

def set_sort_order(sender, **kwargs):
    if isinstance(kwargs['instance'], BaseSortedModel):
        if not getattr(kwargs['instance'], 'sort_order', None):
            kwargs['instance'].sort_order = 0
models.signals.pre_save.connect(set_sort_order)





"""
The same as BaseContentModel, except it requires featured objects to have at least
one inline image (needs a related Image model with related_name 'image_set')
Provides primary_image and random_image methods

Example implementation:

class Article(BaseContentModelWithImages):
    ...

class ArticleImage(models.Model):
    image = models.ImageField(...)
    article = models.ForeignKey(Article, related_name='image_set')
    ...

"""
class BaseContentModelWithImages(BaseContentModel):
    @property
    def primary_image(self):
        try:
            return self.image_set.all()[0]
        except IndexError:
            return None
    
    @property
    def random_image(self):
        try:
            return self.image_set.all().order_by('?')[0]
        except IndexError:
            return None
    class Meta(BaseContentModel.Meta):
        abstract = True
    
    @property
    def image_count(self):
        return self.image_set.count()
    
    objects = models.Manager()
    live = LiveManager()
    featured = FeaturedManagerWithImages()



"""
Provides a simple hierarchy system, for example when categories and subcategories
are needed. Provides get_hierarchy method, which is primarily useful for getting the 
top level category for a given category, eg

>>> category.get_hierarchy()[0]

Currently only 2 levels are supported - in future this will be configurable.
"""
class BaseHierarchyModel(models.Model):
    parent = models.ForeignKey('self', null=True, blank=True, related_name='children', limit_choices_to={'parent__isnull': True})
    
    def __unicode__(self):
        return ' > '.join([c.name for c in self.get_hierarchy()])
    
    def get_parent_display(self):
        return self.parent or ''
    get_parent_display.short_description = 'parent'
    get_parent_display.admin_order_field = 'parent'
    
    def get_hierarchy(self, include_self=True):
        if self.parent:
            return self.parent.get_hierarchy() + (include_self and [self] or [])
        else:
            return include_self and [self] or []
            
    class Meta:
        abstract = True
  
def check_tree(sender, **kwargs):
    if isinstance(kwargs['instance'], BaseHierarchyModel):
        if kwargs['instance'].pk and kwargs['instance'].children.all().count() \
        or kwargs['instance'].parent == kwargs['instance']:
            kwargs['instance'].parent = None
models.signals.pre_save.connect(check_tree)
    
