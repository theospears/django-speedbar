from mixcloud.speedbar.modules.base import RequestTrace

from django.utils.encoding import smart_unicode, smart_str
from django.utils.html import escapejs
from django.core.urlresolvers import reverse

from gargoyle import gargoyle

import re

HTML_TYPES = ('text/html', 'application/xhtml+xml')

METRIC_PLACEHOLDER_RE = re.compile('<span data-module="(?P<module>[^"]+)" data-metric="(?P<metric>[^"]+)"></span>')

class SpeedbarMiddleware(object):
    def process_request(self, request):
        RequestTrace.instance().stacktracer.root.label = '%s %s' % (request.method, request.path)

    def process_response(self, request, response):
        request_trace = RequestTrace.instance()
        metrics = dict((key, module.get_metrics()) for key, module in request_trace.modules.items())

        self.add_response_headers(response, metrics)

        if hasattr(request, 'user') and request.user.is_staff:
            if 'gzip' not in response.get('Content-Encoding', '') and response.get('Content-Type', '').split(';')[0] in HTML_TYPES:

                # Force render of response (from lazy TemplateResponses) before speedbar is injected
                if hasattr(response, 'render'):
                    response.render()
                content = smart_unicode(response.content)

                content = self.replace_templatetag_placeholders(content, metrics)

                # Note: The URLs returned here do not exist at this point. The relevant data is added to the cache by a signal handler
                # once all page processing is finally done. This means it is possible summary values displayed and the detailed
                # break down won't quite correspond.
                if gargoyle.is_active('speedbar:panel', request):
                    panel_url = reverse('speedbar_panel', args=[request_trace.id])
                    content = content.replace(
                        u'<script data-speedbar-panel-url-placeholder></script>',
                        u'<script>var _speedbar_panel_url = "%s";</script>' % (escapejs(panel_url),))
                if gargoyle.is_active('speedbar:trace', request):
                    response['X-TraceUrl'] = reverse('speedbar_trace', args=[request_trace.id])

                response.content = smart_str(content)
                if response.get('Content-Length', None):
                    response['Content-Length'] = len(response.content)
        return response

    def add_response_headers(self, response, metrics):
        """
        Adds all summary metrics to the response headers, so they can be stored in nginx logs if desired.
        """
        def sanitize(string):
            return string.title().replace(' ','-')

        for module, module_values in metrics.items():
            for key, value in module_values.items():
                response['X-Mixcloud-%s-%s' % (sanitize(module), sanitize(key))] = value

    def replace_templatetag_placeholders(self, content, metrics):
        """
        The templatetags defined in this module add placeholder values which we replace with true values here. They
        cannot just insert the values directly as not all processing may have happened by that point.
        """
        def replace_placeholder(match):
            module = match.group('module')
            metric = match.group('metric')
            return unicode(metrics[module][metric])
        return METRIC_PLACEHOLDER_RE.sub(replace_placeholder, content)
