"""Read-only Lead Forensics client. No CRM writes or arbitrary URLs."""
import json
import re
from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

BASE = 'https://interact.leadforensics.com/WebApi_v2/'
ENDPOINTS = {
    'users': 'Reference/GetAssignedToList',
    'recent': 'Business/GetAllBusinesses',
    'assigned': 'Business/GetBusinessesByAssignedTo',
    'business': 'Business/GetBusiness',
    'visits': 'Visit/GetVisitsByBusiness',
    'pages': 'Page/GetPagesByVisit',
}

class LeadForensicsError(Exception):
    pass

class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def window(start=None, end=None):
    if bool(start) != bool(end):
        raise LeadForensicsError('Supply both dates, or omit both for the last seven calendar days.')
    today = datetime.now(ZoneInfo('Europe/London')).date()
    try:
        if start:
            if not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', s) for s in (start, end)):
                raise ValueError()
            first, last = date.fromisoformat(start), date.fromisoformat(end)
        else:
            first, last = today - timedelta(days=6), today
    except (ValueError, TypeError):
        raise LeadForensicsError('Dates must be valid YYYY-MM-DD dates.') from None
    if first > last or (last - first).days > 92:
        raise LeadForensicsError('Use an ordered date range of at most 93 calendar days.')
    return {'datefrom': f'{first} 00:00:00', 'dateto': f'{last} 23:59:59'}

def positive(value, label, maximum=9007199254740991):
    if type(value) is not int or not 1 <= value <= maximum:
        raise LeadForensicsError(f'{label} must be an integer from 1 to {maximum}.')
    return value

class LeadForensics:
    def __init__(self, api_key, client_id):
        self.headers = {'Authorization-Token': api_key, 'ClientID': client_id,
                        'Accept': 'application/json'}
        self.opener = build_opener(NoRedirects())

    def read(self, endpoint, params):
        # Only the six fixed, documented GET endpoints can be requested.
        path = ENDPOINTS[endpoint]
        req = Request(BASE + path + '?' + urlencode(params), headers=self.headers, method='GET')
        try:
            with self.opener.open(req, timeout=25) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise LeadForensicsError('Response too large. Request a smaller page size.')
                return json.loads(body)
        except HTTPError as exc:
            if exc.code in (401, 403):
                message = 'Lead Forensics rejected the credentials or API permissions. Check the hosting secrets.'
            elif exc.code == 429:
                message = 'Lead Forensics rate limit reached. Wait before retrying.'
            else:
                message = f'Lead Forensics returned HTTP {exc.code}. Check the request parameters and API access.'
            # Do not return URLs, response bodies, headers or exception text.
            raise LeadForensicsError(message) from None
        except (URLError, TimeoutError, OSError):
            raise LeadForensicsError('Lead Forensics could not be reached. Try again later.') from None
        except (ValueError, UnicodeError):
            raise LeadForensicsError('Lead Forensics returned an unexpected response format.') from None

    def fetch(self, endpoint, *, start=None, end=None, page=1, page_size=25,
              client_user_id=None, business_id=None, visit_id=None):
        params = {}
        if endpoint != 'business':
            params.update(pageno=positive(page, 'page', 10000),
                          pagesize=positive(page_size, 'page_size', 100))
        if endpoint in ('recent', 'assigned', 'visits'):
            params.update(window(start, end))
        if endpoint == 'assigned':
            params['clientuserid'] = positive(client_user_id, 'client_user_id')
        if endpoint in ('business', 'visits'):
            params['businessid'] = positive(business_id, 'business_id')
        if endpoint == 'pages':
            params['visitid'] = positive(visit_id, 'visit_id')
        payload = self.read(endpoint, params)
        return {
            'source': 'Lead Forensics', 'request': params,
            'coverage': ('Single business record.' if endpoint == 'business' else
                         'One API page only. Request subsequent pages before claiming complete coverage or totals.'),
            'date_note': 'Dates are sent as account-local wall-clock times; confirm the Lead Forensics account timezone.',
            'data': payload,
        }
