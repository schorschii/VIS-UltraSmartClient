"""VIS SOAP login and OData tree access over a shared Kerberos HTTP session."""
from urllib.parse import urlsplit, urlencode, quote, urljoin, unquote
from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr
from pathlib import Path
import tempfile
import base64
import xml.etree.ElementTree as XML
from threading import RLock
import sys

import requests
from defusedxml import ElementTree

# Windows uses SSPI through winkerberos, so MIT Kerberos is not needed there.
if sys.platform == 'win32':
    from .sspi_auth import SSPINegotiateAuth
else:
    import gssapi
    from requests_gssapi import HTTPSPNEGOAuth


def kerberos_auth():
    """Kerberos HTTP authentication answering 401 challenges: SSPI on Windows, GSSAPI elsewhere."""
    if sys.platform == 'win32':
        return SSPINegotiateAuth()
    return HTTPSPNEGOAuth(mech=gssapi.OID.from_int_seq('1.2.840.113554.1.2.2'), opportunistic_auth=False)

SOAP = 'http://www.w3.org/2003/05/soap-envelope'
SERVICE = 'http://services.visj.pdv.de'
USER_INFO_REQUEST = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{SOAP}">
  <soap:Body>
    <getUserInfo xmlns="{SERVICE}">
      <id xmlns="">-1</id>
    </getUserInfo>
  </soap:Body>
</soap:Envelope>'''.encode('utf-8')


TASKS_SESSION_REQUEST = '''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <createServiceSession xmlns="http://services.visj.pdv.de">
      <serviceName xmlns="">STARTSEITEAUFGABEN_SIMPLE_SMART</serviceName>
      <serviceParams xmlns="">
        <entries>
          <key xsi:type="xsd:string">formName</key>
          <value xsi:type="xsd:string">STARTSEITEAUFGABEN_SIMPLE_SMART</value>
        </entries>
        <entries>
          <key xsi:type="xsd:string">boType</key>
          <value xsi:type="xsd:string">19</value>
        </entries>
        <entries>
          <key xsi:type="xsd:string">ignoreErlasser</key>
          <value xsi:type="xsd:boolean">true</value>
        </entries>
        <entries>
          <key xsi:type="xsd:string">richclient.user_and_allstellv</key>
          <value xsi:type="xsd:boolean">true</value>
        </entries>
        <entries>
          <key xsi:type="xsd:string">saveableWithCancel</key>
          <value xsi:type="xsd:string">false</value>
        </entries>
        <entries>
          <key xsi:type="xsd:string">prop_no_message_onempty_search</key>
          <value xsi:type="xsd:string" />
        </entries>
        <entries>
          <key xsi:type="xsd:string">boState</key>
          <value xsi:type="xsd:string">32</value>
        </entries>
        <entries>
          <key xsi:type="xsd:string">PARAM_ADD_COMPLEX_ATTR</key>
          <value xmlns:q1="http://services.visj.pdv.de" xsi:type="q1:xList">
            <entries xsi:type="xsd:string">trefferelemente</entries>
            <version>1</version>
          </value>
        </entries>
        <entries>
          <key xsi:type="xsd:string">mandant</key>
          <value xsi:type="xsd:string">{tenant}</value>
        </entries>
        <version>0</version>
      </serviceParams>
    </createServiceSession>
  </soap:Body>
</soap:Envelope>'''


def parse_soap_body(payload):
    root = ElementTree.fromstring(payload)
    if root.tag != f'{{{SOAP}}}Envelope':
        raise ValueError('Keine SOAP-1.2-Antwort erhalten.')
    body = root.find(f'{{{SOAP}}}Body')
    if body is None:
        raise ValueError('SOAP-Antwort enthält keinen Body.')
    fault = body.find(f'{{{SOAP}}}Fault')
    if fault is not None:
        reason = fault.findtext(f'{{{SOAP}}}Reason/{{{SOAP}}}Text')
        raise ValueError('SOAP-Fehler: ' + (reason or 'Unbekannter Serverfehler'))
    return body


def parse_display_name(payload):
    body = parse_soap_body(payload)
    name = body.findtext(f'{{{SERVICE}}}getUserInfoResponse/return/displayName')
    if not name or not name.strip():
        raise ValueError('SOAP-Antwort enthält keinen Anzeigenamen.')
    return name.strip()


def parse_links(payload):
    body = parse_soap_body(payload)
    result = body.find(f'{{{SERVICE}}}createGetBoSessionResponse/return')
    if result is None:
        raise ValueError('SOAP-Antwort enthält keine Objektsitzung.')
    return [(row.findtext("columns[@identifier='name']/value") or '',
             row.findtext("columns[@identifier='url']/value") or '')
            for row in result.findall("complexAttributes[@identifier='links']/rows")]


def parse_tasks(payload):
    context = parse_soap_body(payload).find(f'{{{SERVICE}}}createGetBoSessionResponse/return')
    if context is None:
        raise ValueError('SOAP-Antwort enthält keine Objektsitzung.')
    return VapiClient.workflow_rows(context)


def parse_reminders(payload):
    return parse_workflow_rows(payload, 'wiedervorlagen')


def parse_workflow_rows(payload, identifier):
    result = parse_soap_body(payload).find(f'{{{SERVICE}}}createGetBoSessionResponse/return')
    if result is None:
        raise ValueError('SOAP-Antwort enthält keine Objektsitzung.')
    return [{column.get('identifier'): column.findtext('value') or ''
             for column in row.findall('columns')}
            for row in result.findall(f"complexAttributes[@identifier='{identifier}']/rows")]


def parse_properties(payload):
    """
    Die Eigenschaften werden aus `simpleAttributes` derselben `createGetBoSession`-Antwort wie Bezüge und Verknüpfungen geladen. `name` liefert die Beschriftung, `value` den Wert und `drawType` die Darstellung als Text, Auswahl oder Checkbox.

    Die Bereiche für Akte, Vorgang, Dokument und Ablage verwenden die jeweils gelieferten Felder, Registratur und Bearbeitung werden separat gruppiert. Beispielsweise liefert `gz` das Geschäftszeichen, `vorgangtyp_id` den Vorgangstyp und `zvarchar` in der vorliegenden Vorgangsantwort „Betreff (Akte)“.
    """
    result = parse_soap_body(payload).find(f'{{{SERVICE}}}createGetBoSessionResponse/return')
    if result is None:
        raise ValueError('SOAP-Antwort enthält keine Objektsitzung.')
    return parse_property_context(result)


def parse_property_context(result):
    return [dict(identifier=attribute.get('identifier', ''),
                 name=attribute.get('name') or attribute.get('identifier', ''),
                 value=attribute.findtext('value') or '',
                 draw_type=attribute.findtext('drawType') or '',
                 behavior=attribute.get('behavior', ''),
                 choice_ids={item.findtext('text') or '': item.findtext('id')
                             for item in (attribute.findall('comboList/itemList') +
                                          [item for combo in result.findall('comboList')
                                           if combo.findtext('identifier') == attribute.get('identifier')
                                           for item in combo.findall('itemList')])},
                 choices=[item.findtext('text') or ''
                          for item in (attribute.findall('comboList/itemList') +
                                       [item for combo in result.findall('comboList')
                                        if combo.findtext('identifier') == attribute.get('identifier')
                                        for item in combo.findall('itemList')])])
            for attribute in result.findall('simpleAttributes')]


def parse_references(payload):
    body = parse_soap_body(payload)
    result = body.find(f'{{{SERVICE}}}createGetBoSessionResponse/return')
    if result is None:
        raise ValueError('SOAP-Antwort enthält keine Objektsitzung.')
    return parse_reference_rows(result.find("complexAttributes[@identifier='bezuege']"))


def parse_reference_rows(collection):
    references = []
    for row in collection.findall('rows') if collection is not None else []:
        values = {column.get('identifier'): column.findtext('value') or ''
                  for column in row.findall('columns')}
        try:
            references.append(ObjectReference(
                int(values['ziel_obj_id']), int(values['objektart_id']),
                values.get('name', ''), values.get('bezugstyp_id', ''),
                values.get('bemerkung', ''), values.get('reihenfolge', ''),
                int(values.get('objekticon_id') or values['objektart_id']), values.get('bez_id', '')))
        except (KeyError, ValueError) as error:
            raise ValueError('Ungültiger Bezug in der Serverantwort.') from error
    return references


@dataclass(frozen=True)
class ObjectReference:
    id: int
    object_kind: int
    name: str
    relation: str
    comment: str
    sequence: str
    icon_id: int = 0
    reference_id: str = ''


@dataclass(frozen=True)
class Repository:
    id: int
    folder_id: int
    name: str
    path: str
    pool_type: int
    typ: int
    pool_id: int | None = None
    child_count: int = 0
    object_kind: int | None = None


def parse_repositories(payload):
    rows, _count, _more = parse_tree_page(payload)
    repositories = []
    for row in rows:
        try:
            identifier = int(row['ObjId'])
            child_count = int(row['ChildCount'])
            if child_count < 0:
                raise ValueError('Negative ChildCount')
            repositories.append(Repository(
                id=identifier, folder_id=identifier,
                name=(row.get('Name') or '').strip() or f'Ablage {identifier}',
                path='', pool_type=int(row['PoolTyp']), typ=int(row['TypId']),
                pool_id=int(row['PoolId']), child_count=child_count,
                object_kind=int(row['ObjektartId']) if row.get('ObjektartId') is not None else None,
            ))
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError('Ungültiger Ablageneintrag in der Serverantwort.') from error
    return repositories


@dataclass(frozen=True)
class TreeItem:
    id: str
    text: str
    has_children: bool
    typ: int
    database_id: str
    icon_name: str
    reference: str = ''
    sequence: str = ''
    short_name: str = ''
    subject: str = ''
    modified: str = ''
    modified_by: str = ''
    object_kind: int | None = None
    icon_id: int = 0
    completed: bool = False


@dataclass(frozen=True)
class ObjectFile:
    name: str
    file_id: int
    bo_id: int
    path: str
    size: int
    flags: int
    modified: str
    modified_by: str
    created: str
    created_by: str
    comment: str
    rendition_types: str
    rights: int


class VapiClient:
    """One tenant's HTTP connections and in-memory cookies, shared by its windows.

    Calls are serialized because requests.Session and GSSAPI auth have mutable
    state. Challenge-based authentication lets valid cookies avoid a new GSSAPI
    exchange; a 401 Negotiate challenge triggers authentication when needed.
    """
    def __init__(self, server_url, debug=False):
        url = urlsplit(server_url)
        if (url.scheme not in ('http', 'https') or not url.hostname
                or url.username is not None or url.password is not None or url.query or url.fragment):
            raise ValueError('Bitte eine HTTP(S)-Server-Basis-URL ohne Zugangsdaten, Query oder Fragment angeben.')
        self.server_url = server_url.rstrip('/')
        self.debug = debug
        self.command_message_handler = None
        self.user_id = None
        self.main_user_id = None
        self.stellvertreter = []
        self.selected_stellvertreter_id = -10000
        self.stellvertreter_error = ''
        self.user_picture = b''
        self.tasks_session_id = None
        self.tasks_version = 0
        self._lock = RLock()
        self._closed = False
        self.session = requests.Session()
        self.session.auth = kerberos_auth()

    def close(self):
        with self._lock:
            if not self._closed:
                self.session.close()
                self.session.cookies.clear()
                self._closed = True

    def soap_request(self, service, payload):
        with self._lock:
            if self._closed:
                raise RuntimeError('Die VIS-Verbindung ist geschlossen.')
            endpoint = self.server_url + '/service/' + service
            if self.debug:
                body = payload.decode('utf-8', errors='replace') if isinstance(payload, bytes) else payload
                print(f'>>> SOAP REQUEST {endpoint}\n{body}\n', flush=True)
            response = self.session.post(
                endpoint, data=payload,
                headers={'Content-Type': 'application/soap+xml; charset=utf-8'},
                timeout=(10, 30), allow_redirects=False,
            )
            if self.debug:
                body = response.content.decode(response.encoding or 'utf-8', errors='replace')
                print(f'<<< SOAP RESPONSE {endpoint} HTTP {response.status_code}\n{body}\n', flush=True)
        if response.status_code == 401:
            raise ValueError('Kerberos-Anmeldung fehlgeschlagen. Ticket mit klist/kinit prüfen.')
        if 300 <= response.status_code < 400:
            raise ValueError('Server leitet um. Bitte die direkte Server-Basis-URL konfigurieren.')
        # SOAP faults commonly arrive with HTTP 500; preserve their reason.
        if response.status_code == 500:
            try:
                parse_soap_body(response.content)
            except ValueError as error:
                if str(error).startswith('SOAP-Fehler:'):
                    raise
            except ElementTree.ParseError:
                pass
        response.raise_for_status()
        if b'startCommandResponse' in response.content:
            self._handle_command_messages(response.content)
        return response.content

    def _handle_command_messages(self, payload):
        body = parse_soap_body(payload)
        errors = []
        for operation in body.findall(f'{{{SERVICE}}}startCommandResponse'):
            for container in operation.iter():
                if container.tag.rsplit('}', 1)[-1] != 'messages':
                    continue
                for message in container:
                    if message.tag.rsplit('}', 1)[-1] != 'messages':
                        continue
                    text = '\n'.join(''.join(node.itertext()).strip() for node in message
                                     if node.tag.rsplit('}', 1)[-1] == 'text')
                    text = text or 'Der Server hat eine Meldung ohne Text geliefert.'
                    is_error = message.get('type') == '3'
                    if self.command_message_handler is not None:
                        self.command_message_handler(text, is_error)
                    if is_error:
                        errors.append(text)
        if errors:
            raise ValueError('\n'.join(errors))


    def switch_stellvertreter(self, user_id):
        with self._lock:
            payload = f'<s:Envelope xmlns:s="{SOAP}"><s:Body><setStellvertreterFuer xmlns="{SERVICE}"><adm_id xmlns="">{int(user_id)}</adm_id></setStellvertreterFuer></s:Body></s:Envelope>'
            body = parse_soap_body(self.soap_request('UserRepository', payload.encode()))
            if body.find(f'{{{SERVICE}}}setStellvertreterFuerResponse') is None:
                raise ValueError('Der Server hat den Stellvertreterwechsel nicht bestätigt.')
            self.selected_stellvertreter_id = int(user_id)
            self.tasks_session_id = None
            self.tasks_version = 0
            self.user_picture = b''
            name = self.fetch_display_name(user_id if int(user_id) != -10000 else -1)
            warnings = []
            try:
                self.fetch_user_picture()
            except Exception as error:
                warnings.append(str(error))
            try:
                self.fetch_stellvertreter()
            except Exception as error:
                self.stellvertreter = []
                self.stellvertreter_error = str(error)
                warnings.append(str(error))
            return {'name': name, 'warnings': warnings}

    def fetch_stellvertreter(self):
        payload = f'''<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>
<getStellvertreterFuerList xmlns="{SERVICE}"/></soap:Body></soap:Envelope>'''.encode('utf-8')
        body = parse_soap_body(self.soap_request('UserRepository', payload))
        response = body.find(f'{{{SERVICE}}}getStellvertreterFuerListResponse')
        if response is None:
            raise ValueError('Der Server hat keine Stellvertreterliste geliefert.')
        entries = []
        for row in response.findall('return'):
            user_id = int(row.findtext('id'))
            name = (row.findtext('displayName') or row.findtext('anredeName')
                    or row.findtext('userName') or row.findtext('name') or str(user_id))
            entries.append({'id': user_id, 'name': name, 'stelle': row.findtext('stelle') or '',
                            'active': row.findtext('active') in ('true', '1')})
        self.stellvertreter = entries
        self.stellvertreter_error = ''
        return entries

    def fetch_user_picture(self):
        self.user_picture = b''
        if self.user_id is None:
            raise ValueError('Für das Benutzerbild fehlt die Benutzer-ID.')
        payload = f'''<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>
<getUserPicture xmlns="{SERVICE}"><id xmlns="">{int(self.user_id)}</id></getUserPicture>
</soap:Body></soap:Envelope>'''.encode('utf-8')
        body = parse_soap_body(self.soap_request('UserRepository', payload))
        response = body.find(f'{{{SERVICE}}}getUserPictureResponse')
        if response is None:
            raise ValueError('Der Server hat kein Benutzerbild geliefert.')
        encoded = ''.join((response.findtext('return') or '').split())
        self.user_picture = base64.b64decode(encoded, validate=True)
        return self.user_picture

    def set_user_picture(self, data):
        encoded = base64.b64encode(data).decode('ascii')
        payload = f'''<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>
<setUserPicture xmlns="{SERVICE}"><data xmlns="">{encoded}</data></setUserPicture>
</soap:Body></soap:Envelope>'''.encode('utf-8')
        body = parse_soap_body(self.soap_request('UserRepository', payload))
        if body.find(f'{{{SERVICE}}}setUserPictureResponse') is None:
            raise ValueError('Der Server hat die Änderung des Benutzerbilds nicht bestätigt.')
        self.user_picture = data

    def fetch_display_name(self, user_id=-1):
        request = USER_INFO_REQUEST.replace(b'>-1</id>', f'>{int(user_id)}</id>'.encode())
        payload = self.soap_request('UserRepository', request)
        name = parse_display_name(payload)
        self.user_id = parse_soap_body(payload).findtext(f'{{{SERVICE}}}getUserInfoResponse/return/id')
        if int(user_id) == -1:
            self.main_user_id = self.user_id
        return name

    def fetch_links(self, object_id, object_kind):
        return self.fetch_object_relations(object_id, object_kind)[0]

    def fetch_object_relations(self, object_id, object_kind):
        return self.fetch_object_details(object_id, object_kind)[:2]

    def fetch_object_details(self, object_id, object_kind):
        payload = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{SOAP}">
  <soap:Body>
    <createGetBoSession xmlns="{SERVICE}">
      <obj_id xmlns="">{int(object_id)}</obj_id>
      <obj_typ xmlns="">{int(object_kind)}</obj_typ>
    </createGetBoSession>
  </soap:Body>
</soap:Envelope>'''.encode('utf-8')
        response = self.soap_request('SessionObject', payload)
        return parse_links(response), parse_references(response), parse_properties(response), parse_tasks(response), parse_reminders(response), parse_workflow_rows(response, 'historienelemente')

    def fetch_new_object_kinds(self, parent):
        with self._lock:
            context = self.workflow_call('createGetBoSession',
                f'<obj_id xmlns="">{int(parent["id"])}</obj_id><obj_typ xmlns="">{int(parent["object_kind"])}</obj_typ>').find('return')
            if context is None:
                raise ValueError('Keine Objektsitzung vorhanden.')
            attributes = {a.get('identifier'): a for a in context.findall('simpleAttributes')}
            pool = attributes.get('pool_id')
            if pool is None or pool.get('idvalue') is None:
                raise ValueError('Der Speicherort enthält keine Ablage-ID.')
            type_key = {1: 'aktentyp_id', 2: 'ablagetyp_id', 3: 'vorgangtyp_id'}.get(parent['object_kind'], 'dokumenttyp_id')
            typ = attributes.get(type_key)
            type_id = typ.get('idvalue') if typ is not None else parent.get('typ')
            payload = f'<s:Envelope xmlns:s="{SOAP}"><s:Body><getObjektartInhaltChildList xmlns="{SERVICE}"><objektartId xmlns="">{int(parent["object_kind"])}</objektartId><typId xmlns="">{int(type_id)}</typId></getObjektartInhaltChildList></s:Body></s:Envelope>'
            body = parse_soap_body(self.soap_request('MandantenRepository', payload.encode()))
            result = body.find(f'{{{SERVICE}}}getObjektartInhaltChildListResponse/return')
            if result is None:
                raise ValueError('Keine Objektarten geliefert.')
            return {'pool_id': int(pool.get('idvalue')), 'kinds': [
                (item.findtext('text') or '', int(item.findtext('id'))) for item in result.findall('itemList')]}

    def load_new_object_types(self, object_kind, parent_id, pool_id, previous=None):
        with self._lock:
            if previous:
                self.cancel_workflow_editor(previous)
            context = self.workflow_call('createNewBoSession',
                f'<obj_typ xmlns="">{int(object_kind)}</obj_typ><parent_id xmlns="">{int(parent_id)}</parent_id>'
                f'<pool_id xmlns="">{int(pool_id)}</pool_id><param xmlns=""><version>0</version></param>').find('return')
            if context is None or not context.get('instanceId'):
                raise ValueError('Keine Sitzung für das neue Objekt geliefert.')
            key = {1: 'aktentyp_id', 2: 'ablagetyp_id', 3: 'vorgangtyp_id'}.get(int(object_kind), 'dokumenttyp_id')
            type_attribute = context.find("simpleAttributes[@identifier='" + key + "']")
            return {'session_id': context.get('instanceId'), 'object_kind': int(object_kind),
                    'type_key': key, 'type_id': type_attribute.get('idvalue') if type_attribute is not None else None,
                    'type_comcode': int(type_attribute.findtext('comcode') or 0) if type_attribute is not None else 0,
                    'attributes': parse_property_context(context),
                    'object_id': context.findtext("simpleAttributes[@identifier='obj_id']/value"),
                    'subject': context.findtext("simpleAttributes[@identifier='betreff']/value") or '', 'types': [
                (item.findtext('text') or '', item.findtext('id'))
                for combo in context.findall('comboList') if combo.findtext('identifier') == key
                for item in combo.findall('itemList')]}

    def select_new_object_type(self, editor, type_id):
        """Apply a type change to a new-object session and return the attributes available for that type.

        Types have type-specific fields, so the server is told about the change through the
        type field's own command code; the changed context then lists the attributes of that type.
        """
        if str(type_id) not in [str(identifier) for name, identifier in editor['types']]:
            raise ValueError('Ungültiger Objekttyp.')
        if str(type_id) == str(editor.get('type_id')) or not editor.get('type_comcode'):
            return editor['attributes']
        with self._lock:
            session = editor['session_id']
            command = editor['type_comcode']
            result = self.property_command(session, command, changes={editor['type_key']: str(type_id)})
            context = result.find('changedSessionContext') if result is not None else None
            self.property_command(session, command, 'endCommand')
            if context is None or context.find('simpleAttributes') is None:
                response = self.workflow_call('getAttributes', f'<sessionid xmlns="">{escape(session)}</sessionid>')
                context = response.find('return')
            if context is not None and context.find('simpleAttributes') is not None:
                attributes = {a['identifier']: a for a in editor['attributes']}
                attributes.update((a['identifier'], a) for a in parse_property_context(context))
                editor['attributes'] = list(attributes.values())
            editor['type_id'] = str(type_id)
            return editor['attributes']

    def create_object(self, editor, type_id, subject, fields=None):
        if not subject.strip():
            raise ValueError('Bitte einen Betreff eingeben.')
        if str(type_id) not in [str(identifier) for name, identifier in editor['types']]:
            raise ValueError('Ungültiger Objekttyp.')
        with self._lock:
            session = editor['session_id']
            changes = {**(fields or {}), 'betreff': subject.strip()}
            # Combo fields use their selected server ID, as in property editing.
            if str(type_id) != str(editor.get('type_id')):
                changes[editor['type_key']] = str(type_id)
            object_id = editor.get('object_id')
            for command in (1002, 1007):
                for operation in ('startCommand', 'endCommand'):
                    result = self.property_command(session, command, operation,
                        changes=changes if command == 1002 and operation == 'startCommand' else None)
                    context = result.find('changedSessionContext') if result is not None else None
                    if context is not None:
                        object_id = context.findtext("simpleAttributes[@identifier='obj_id']/value") or object_id
            if not object_id:
                raise ValueError('Objekt angelegt, aber der Server hat keine Objekt-ID geliefert. Bitte die Ablage neu laden.')
            kind = editor['object_kind']
            return dict(id=int(object_id), name=subject.strip(), object_kind=kind,
                        typ=int(type_id), icon_id=kind, repository=False)

    def search_objects(self, query):
        tenant = unquote(urlsplit(self.server_url).path.rstrip('/').rsplit('/', 1)[-1]).strip('{}')
        payload = {'offset': 0, 'num': 100, 'query': query, 'filter': [],
                   'fieldQueries': [], 'facets': [], 'facetFilter': [], 'sortby': None, 'sortdir': 'asc'}
        with self._lock:
            if self._closed:
                raise RuntimeError('Die VIS-Verbindung ist geschlossen.')
            response = self.session.post(self.server_url + '/vis_search/searching/simple',
                params={'client': tenant}, json=payload, headers={'Accept': 'application/json'},
                timeout=(10, 30), allow_redirects=False)
            if response.status_code == 401:
                raise ValueError('Kerberos-Anmeldung fehlgeschlagen.')
            if 300 <= response.status_code < 400:
                raise ValueError('Such-Endpunkt leitet um. Bitte die Server-Basis-URL prüfen.')
            response.raise_for_status()
            data = response.json()
        entries, total = [], 0
        for result in data['resultset']['results']:
            if result.get('errorcode', 200) != 200 or result.get('aborted'):
                raise ValueError(result.get('abortCause') or 'Die Suche ist fehlgeschlagen.')
            total += int(result.get('num', 0))
            for group in result.get('groups', []):
                for document in group.get('documents', []):
                    fields = {field['name']: field.get('value') for field in document['fields']}
                    kind = int(fields['objektart_id'])
                    name = fields.get('name') or fields.get('objekt_name') or fields.get('kurzbez') or fields.get('gz') or str(fields['obj_id'])
                    entries.append(dict(id=int(fields['obj_id']), name=name, typ=kind, object_kind=kind,
                        icon_id=int(fields.get('doctype') or kind), repository=False,
                        file_id=fields.get('vfs_id'), score=float(fields.get('score') or 0)))
        return entries, total

    def tree_get(self, url):
        """Authenticated GET with an empty body and Atom/XML response."""
        with self._lock:
            if self._closed:
                raise RuntimeError('Die VIS-Verbindung ist geschlossen.')
            if self.debug:
                print(f'>>> TREE GET {url}', flush=True)
            response = self.session.get(
                url, headers={'Accept': 'application/atom+xml,application/xml'},
                timeout=(10, 30), allow_redirects=False)
            if self.debug:
                print(f'<<< TREE RESPONSE {url} HTTP {response.status_code}\n'
                      f'{response.content.decode(response.encoding or "utf-8", errors="replace")}\n', flush=True)
        if response.status_code == 401:
            raise ValueError('Kerberos-Anmeldung fehlgeschlagen. Ticket mit klist/kinit prüfen.')
        if 300 <= response.status_code < 400:
            raise ValueError('Baum-Endpunkt leitet um. Bitte die Server-Basis-URL prüfen.')
        response.raise_for_status()
        return response.content

    def create_tasks_session(self):
        # Tenant URLs end in the tenant identifier; never reuse the sample tenant.
        tenant = unquote(urlsplit(self.server_url).path.rstrip('/').rsplit('/', 1)[-1])
        if not tenant:
            raise ValueError('Die Server-URL enthält keinen Mandanten.')
        tenant = '{' + tenant.strip('{}') + '}'
        payload = TASKS_SESSION_REQUEST.replace('{tenant}', escape(tenant)).encode('utf-8')
        body = parse_soap_body(self.soap_request('SessionObject', payload))
        context = body.find(f'{{{SERVICE}}}createServiceSessionResponse/return')
        session_id = context.get('instanceId') if context is not None else None
        if not session_id:
            raise ValueError('SOAP-Antwort enthält keine Aufgaben-Sitzungs-ID.')
        self.tasks_session_id = session_id
        self.tasks_version = 0

    def fetch_my_tasks(self):
        with self._lock:
            if not self.tasks_session_id:
                self.create_tasks_session()
            payload = f'''<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>
<startCommand xmlns="{SERVICE}"><sessionid xmlns="">{escape(self.tasks_session_id)}</sessionid>
<commandid xmlns="">1470100018</commandid><changedAttributes xmlns=""/>
<param xmlns=""><version>{self.tasks_version}</version></param>
</startCommand></soap:Body></soap:Envelope>'''.encode('utf-8')
            body = parse_soap_body(self.soap_request('SessionObject', payload))
            result = body.find(f'{{{SERVICE}}}startCommandResponse/return')
            context = result.find('changedSessionContext') if result is not None else None
            if context is None:
                raise ValueError('SOAP-Antwort enthält keine Aufgabenübersicht.')
            rows = [{column.get('identifier'): column.findtext('value') or ''
                     for column in row.findall('columns')}
                    for row in context.findall("complexAttributes[@identifier='trefferelemente']/rows")]
            version = result.findtext('serviceParams/version')
            if version is not None:
                self.tasks_version = int(version)
            self.tasks_session_id = context.get('instanceId') or self.tasks_session_id
            return rows

    def fetch_favorites(self, admin_id=171, folder_id=None):
        endpoint = self.server_url + '/vistree/Favoritens()'
        if folder_id is None:
            params = {'$filter': f'AdmId eq {int(admin_id)}L and VaterId eq 0L and (ArtId eq -1L or ArtId eq 0L)',
                      '$orderby': 'Reihenfolge'}
        else:
            params = {'$top': 1, '$filter': f'Id eq {int(folder_id)}L'}
        entries = self._favorite_entries(endpoint, params)
        # A standard OData Id lookup returns the folder itself. Resolve its children
        # by parent ID in that case; some servers return the contents directly.
        if folder_id is not None and any(e['favorite_id'] == int(folder_id) and e['folder'] for e in entries):
            entries = self._favorite_entries(endpoint, {
                '$filter': f'AdmId eq {int(admin_id)}L and VaterId eq {int(folder_id)}L and (ArtId eq -1L or ArtId eq 0L)',
                '$orderby': 'Reihenfolge'})
        return entries

    def add_favorite(self, object_id, name, parent_favorite_id=0, position=-1):
        payload = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{SOAP}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <AddBOFavorite xmlns="{SERVICE}">
      <obj_id xmlns="">{int(object_id)}</obj_id>
      <name xmlns="">{escape(str(name))}</name>
      <position xmlns="">{int(position)}</position>
      <parent_fav_id xmlns="">{int(parent_favorite_id)}</parent_fav_id>
    </AddBOFavorite>
  </soap:Body>
</soap:Envelope>'''.encode('utf-8')
        parse_soap_body(self.soap_request('Favorites', payload))

    def create_favorite_folder(self, name, parent_favorite_id=0, position=-1):
        payload = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{SOAP}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <CreateFolder xmlns="{SERVICE}">
      <name xmlns="">{escape(str(name))}</name>
      <position xmlns="">{int(position)}</position>
      <parent_fav_id xmlns="">{int(parent_favorite_id)}</parent_fav_id>
    </CreateFolder>
  </soap:Body>
</soap:Envelope>'''.encode('utf-8')
        parse_soap_body(self.soap_request('Favorites', payload))

    def delete_favorite(self, favorite_id):
        payload = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{SOAP}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <Delete xmlns="{SERVICE}">
      <fav_id xmlns="">{int(favorite_id)}</fav_id>
    </Delete>
  </soap:Body>
</soap:Envelope>'''.encode('utf-8')
        parse_soap_body(self.soap_request('Favorites', payload))

    def _favorite_entries(self, endpoint, params):
        url = endpoint + '?' + urlencode(params, quote_via=quote, safe='$,()')
        entries, seen = [], set()
        for payload in self.feed_pages(url, endpoint):
            rows, _count, _more = parse_tree_page(payload)
            for row in rows:
                try:
                    identifier, object_id = int(row['Id']), int(row['ObjId'])
                    entry = dict(favorite_id=identifier, id=object_id, name=row.get('Name') or str(identifier),
                                 folder=object_id == -1, typ=int(row['ObjekttypId']),
                                 object_kind=int(row['ObjektartId']), icon_id=int(row.get('ObjekticonId') or 0),
                                 repository=False, order=int(row.get('Reihenfolge') or 0),
                                 container=object_id != -1)
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError('Ungültiger Favoriteneintrag in der Serverantwort.') from error
                if identifier in seen:
                    raise ValueError('Wiederholte Favoriten-ID in der Serverantwort.')
                seen.add(identifier)
                entries.append(entry)
        return sorted(entries, key=lambda entry: entry['order'])

    def fetch_repositories(self):
        return self.fetch_tree_items()

    def fetch_tree_items(self):
        """Load the top-level Ablages, using ObjId rather than PoolId as tree ID."""
        endpoint = self.server_url + '/vistree/Ablages()'
        url = endpoint + '?' + urlencode({'$filter': 'TypId eq 2L', '$orderby': 'Name'},
                                         quote_via=quote, safe='$,')
        repositories, identifiers = [], set()
        for payload in self.feed_pages(url, endpoint):
            for repository in parse_repositories(payload):
                if repository.id in identifiers:
                    raise ValueError('Wiederholte Objekt-ID in der Ablagenantwort.')
                identifiers.add(repository.id)
                repositories.append(repository)
        return repositories

    def feed_pages(self, url, endpoint):
        visited = set()
        while url:
            if url in visited:
                raise ValueError('Wiederholte Folgeseite in der Serverantwort.')
            visited.add(url)
            payload = self.tree_get(url)
            yield payload
            feed = ElementTree.fromstring(payload)
            next_link = next((link.get('href') for link in feed.findall(f'{{{ATOM}}}link')
                              if link.get('rel') == 'next'), None)
            if next_link:
                next_url = urljoin(url, next_link)
                target, base = urlsplit(next_url), urlsplit(endpoint)
                if (target.scheme != base.scheme or target.netloc != base.netloc
                        or target.path not in (base.path, base.path.removesuffix('()'))
                        or target.fragment):
                    raise ValueError('Ungültige Folgeseiten-URL in der Serverantwort.')
                url = next_url
            else:
                url = None

    def fetch_files(self, bo_id):
        bo_id = int(bo_id)
        endpoint = self.server_url + '/vistree/Files()'
        params = {
            '$filter': f'BoId eq {bo_id}L',
            '$select': 'Name,FileId,BoId,Path,Filesize,Flags,Modified,ModifiedBy,Created,CreatedBy,Objcomment,Renditiontypes,Rights',
        }
        url = endpoint + '?' + urlencode(params, quote_via=quote, safe='$,')
        files, identifiers = [], set()
        for payload in self.feed_pages(url, endpoint):
            rows, _count, _more = parse_tree_page(payload)
            for row in rows:
                try:
                    file = ObjectFile(
                        name=row.get('Name') or '', file_id=int(row['FileId']),
                        bo_id=int(row['BoId']), path=row.get('Path') or '',
                        size=int(row['Filesize']), flags=int(row['Flags']),
                        modified=row.get('Modified') or '', modified_by=row.get('ModifiedBy') or '',
                        created=row.get('Created') or '', created_by=row.get('CreatedBy') or '',
                        comment=row.get('Objcomment') or '', rendition_types=row.get('Renditiontypes') or '',
                        rights=int(row['Rights']),
                    )
                    if file.size < 0 or file.bo_id != bo_id or file.file_id in identifiers:
                        raise ValueError('Unpassender oder doppelter Dateieintrag')
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError('Ungültiger Dateieintrag in der Serverantwort.') from error
                identifiers.add(file.file_id)
                files.append(file)
        return files

    def workflow_call(self, operation, content):
        payload = f'''<s:Envelope xmlns:s="{SOAP}" xmlns:ns2="{SERVICE}" xmlns:q1="{SERVICE}"
xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsd="http://www.w3.org/2001/XMLSchema"
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><s:Body><{operation} xmlns="{SERVICE}">
{content}</{operation}></s:Body></s:Envelope>'''.encode()
        reply = self.soap_request('SessionObject', payload)
        # VIS may return an empty body for a combo without any suggestions.
        if operation == 'getComboList' and not reply.strip():
            return XML.Element(f'{{{SERVICE}}}{operation}Response')
        body = parse_soap_body(reply)
        response = body.find(f'{{{SERVICE}}}{operation}Response')
        if response is None:
            raise ValueError('Ungültige Serverantwort für die Geschäftsgangverfügung.')
        return response

    @staticmethod
    def workflow_params(params, tag='serviceParams'):
        copy = XML.fromstring(XML.tostring(params))
        copy.tag = tag
        copy.set('xmlns', '')
        version = copy.find('version')
        if version is not None:
            version.text = '0'
        return XML.tostring(copy, encoding='unicode')

    @staticmethod
    def workflow_rows(context):
        return [dict({column.get('identifier'): column.findtext('value') or ''
                      for column in row.findall('columns')},
                     _category_choices=[(item.findtext('text'), item.findtext('id')) for item in
                         row.findall("columns[@identifier='kategorie']/comboList/itemList")],
                     _category_ids={c.get('identifier'): c.get('idvalue') for c in row.findall('columns')
                                    if c.get('identifier') in ('kategorie', 'kategorie_typ', 'pkg_kategorie')},
                     _session_index=row.get('index'),
                     _assignee_id=row.find("columns[@identifier='erlassen_fuer_id']").get('idvalue')
                     if row.find("columns[@identifier='erlassen_fuer_id']") is not None else None)
                for row in context.findall("complexAttributes[@identifier='ggvermerke']/rows")]

    def create_workflow_task(self, object_id, object_kind, state=None):
        return self._create_workflow_entry(object_id, object_kind, state, 3010)

    def create_reminder(self, object_id, object_kind, state=None):
        return self._create_workflow_entry(object_id, object_kind, state, 3008)

    @staticmethod
    def reminder_rows(context):
        return [dict({column.get('identifier'): column.findtext('value') or ''
                      for column in row.findall('columns')}, _session_index=row.get('index'))
                for row in context.findall("complexAttributes[@identifier='wiedervorlagen']/rows")]

    def _create_workflow_entry(self, object_id, object_kind, state, command_id):
        with self._lock:
            if state is None:
                response = self.workflow_call('createGetBoSession',
                    f'<obj_id xmlns="">{int(object_id)}</obj_id><obj_typ xmlns="">{int(object_kind)}</obj_typ>')
                context = response.find('return')
                if context is None or not context.get('instanceId'):
                    raise ValueError('Keine Objektsitzung vorhanden.')
                state = {'session_id': context.get('instanceId'), 'attributes': parse_property_context(context),
                         'tasks': self.workflow_rows(context), 'reminders': self.reminder_rows(context)}
            state = dict(state)
            for operation in ('startCommand', 'endCommand'):
                result = self.property_command(state['session_id'], command_id, operation,
                    changes={'auslauf': ''} if command_id == 3008 else None)
                context = result.find('changedSessionContext') if result is not None else None
                if context is not None:
                    if context.findall('simpleAttributes'):
                        state['attributes'] = parse_property_context(context)
                    if context.find("complexAttributes[@identifier='ggvermerke']") is not None:
                        state['tasks'] = self.workflow_rows(context)
                    if context.find("complexAttributes[@identifier='wiedervorlagen']") is not None:
                        state['reminders'] = self.reminder_rows(context)
            state['workflow'] = True
            return state

    def delete_workflow_task(self, object_id, object_kind, state, index):
        return self._delete_workflow_row(state, index, 'tasks', 'ggvermerke', 3004)

    def delete_reminder(self, object_id, object_kind, state, index):
        return self._delete_workflow_row(state, index, 'reminders', 'wiedervorlagen', 3021)

    def _delete_workflow_row(self, state, index, key, identifier, command_id):
        with self._lock:
            if state is None:
                raise ValueError('Bitte zuerst den Bearbeitungsmodus aktivieren.')
            index = int(index)
            if index < 0 or not any(str(row.get('_session_index')) == str(index) for row in state.get(key, [])):
                raise ValueError('Der Eintrag ist nicht mehr vorhanden. Bitte neu laden.')
            selection = f'''<complexAttributes behavior="0" identifier="{identifier}">
<rows focused="false" selected="true" style="0" styleColor="0" visible="false" index="{index}" dragDropDataObjId="0" dragDropTyp="0" uniqueId="0">
<columns identifier="__select" idvalue="0" maxLength="0" behavior="0"><value>1</value>
<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode><changeTyp>3</changeTyp>
<master>false</master><slave>false</slave></columns></rows></complexAttributes>'''
            updated = dict(state)
            updated[key] = [row for row in state[key] if str(row.get('_session_index')) != str(index)]
            prefix = f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><commandid xmlns="">{command_id}</commandid>'
            for operation, content in (
                ('startCommand', f'<changedAttributes xmlns="">{selection}</changedAttributes><param xmlns=""><version>0</version></param>'),
                ('endCommand', '<serviceParams xmlns=""><version>0</version></serviceParams>')):
                result = self.workflow_call(operation, prefix + content).find('return')
                if result is not None and result.get('serviceName'):
                    raise ValueError('Der Server hat das Löschen nicht bestätigt.')
                context = result.find('changedSessionContext') if result is not None else None
                if context is not None:
                    if context.findall('simpleAttributes'):
                        updated['attributes'] = parse_property_context(context)
                    if operation == 'endCommand':
                        for name, collection, parser in (('tasks', 'ggvermerke', self.workflow_rows),
                                                         ('reminders', 'wiedervorlagen', self.reminder_rows)):
                            if context.find(f"complexAttributes[@identifier='{collection}']") is not None:
                                updated[name] = parser(context)
            return updated

    def delete_link(self, object_id, object_kind, state, link):
        """Stage link removal in the object session; saving remains explicit."""
        with self._lock:
            if state is None:
                context = self.workflow_call('createGetBoSession',
                    f'<obj_id xmlns="">{int(object_id)}</obj_id><obj_typ xmlns="">{int(object_kind)}</obj_typ>').find('return')
                if context is None or not context.get('instanceId'):
                    raise ValueError('Keine Objektsitzung vorhanden.')
                state = {'session_id': context.get('instanceId'), 'attributes': parse_property_context(context),
                         'tasks': self.workflow_rows(context), 'reminders': self.reminder_rows(context)}
                collection = context.find("complexAttributes[@identifier='links']")
            else:
                collection = self.workflow_call('getComplexAttribute',
                    f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><identifier xmlns="">links</identifier>').find('return')
            rows = collection.findall('rows') if collection is not None else []
            def values(row):
                return (row.findtext("columns[@identifier='name']/value") or '',
                        row.findtext("columns[@identifier='url']/value") or '')
            matches = [row for row in rows if values(row) == tuple(link)]
            if len(matches) != 1:
                raise ValueError('Die Verknüpfung ist nicht mehr eindeutig vorhanden. Bitte neu laden.')
            selected = matches[0]
            index = int(selected.get('index', '-1'))
            if index < 0:
                raise ValueError('Ungültiger Verknüpfungsindex.')
            selection = f'''<complexAttributes behavior="0" identifier="links">
<rows focused="false" selected="true" style="0" styleColor="0" visible="false" index="{index}" dragDropDataObjId="0" dragDropTyp="0" uniqueId="0">
<columns identifier="__select" idvalue="0" maxLength="0" behavior="0"><value>1</value>
<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode><changeTyp>3</changeTyp>
<master>false</master><slave>false</slave></columns></rows></complexAttributes>'''
            state = dict(state)
            state['links'] = [values(row) for row in rows if row is not selected]
            prefix = f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><commandid xmlns="">3014</commandid>'
            for operation, content in (
                ('startCommand', f'<changedAttributes xmlns="">{selection}</changedAttributes><param xmlns=""><version>0</version></param>'),
                ('endCommand', '<serviceParams xmlns=""><version>0</version></serviceParams>')):
                result = self.workflow_call(operation, prefix + content).find('return')
                if result is not None and result.get('serviceName'):
                    raise ValueError('Der Server hat das Löschen der Verknüpfung nicht bestätigt.')
                context = result.find('changedSessionContext') if result is not None else None
                if context is not None:
                    if context.findall('simpleAttributes'):
                        state['attributes'] = parse_property_context(context)
                    changed_links = context.find("complexAttributes[@identifier='links']")
                    if changed_links is not None:
                        state['links'] = [values(row) for row in changed_links.findall('rows')]
            return state

    def delete_references(self, object_id, object_kind, state, references):
        """Stage reference removal in the object session; saving remains explicit."""
        with self._lock:
            if state is None:
                context = self.workflow_call('createGetBoSession',
                    f'<obj_id xmlns="">{int(object_id)}</obj_id><obj_typ xmlns="">{int(object_kind)}</obj_typ>').find('return')
                if context is None or not context.get('instanceId'):
                    raise ValueError('Keine Objektsitzung vorhanden.')
                state = {'session_id': context.get('instanceId'), 'attributes': parse_property_context(context),
                         'tasks': self.workflow_rows(context), 'reminders': self.reminder_rows(context)}
                collection = context.find("complexAttributes[@identifier='bezuege']")
            else:
                collection = self.workflow_call('getComplexAttribute',
                    f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><identifier xmlns="">bezuege</identifier>').find('return')
            rows = collection.findall('rows') if collection is not None else []
            if not references:
                raise ValueError('Bitte zuerst einen Bezug auswählen.')
            current = parse_reference_rows(collection)
            selected = []
            for reference in references:
                matches = [row for row, value in zip(rows, current)
                           if (value.reference_id == reference.reference_id if reference.reference_id else value == reference)]
                if len(matches) != 1 or matches[0] in selected:
                    raise ValueError('Der Bezug ist nicht mehr eindeutig vorhanden. Bitte neu laden.')
                selected.append(matches[0])
            indices = [int(row.get('index', '-1')) for row in selected]
            if any(index < 0 for index in indices) or len(set(indices)) != len(indices):
                raise ValueError('Ungültiger Bezugsindex.')
            selection_rows = ''.join(f'''
<rows focused="false" selected="true" style="0" styleColor="0" visible="false" index="{index}" dragDropDataObjId="0" dragDropTyp="0" uniqueId="0">
<columns identifier="__select" idvalue="0" maxLength="0" behavior="0"><value>1</value>
<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode><changeTyp>3</changeTyp>
<master>false</master><slave>false</slave></columns></rows>''' for index in indices)
            selection = f'<complexAttributes behavior="0" identifier="bezuege">{selection_rows}</complexAttributes>'
            state = dict(state)
            state['references'] = [value for row, value in zip(rows, current) if row not in selected]
            prefix = f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><commandid xmlns="">3007</commandid>'
            for operation, content in (
                ('startCommand', f'<changedAttributes xmlns="">{selection}</changedAttributes><param xmlns=""><version>0</version></param>'),
                ('endCommand', '<serviceParams xmlns=""><entries><key xsi:type="xsd:string">messagereturn</key><value xsi:type="xsd:byte">1</value></entries><version>0</version></serviceParams>')):
                result = self.workflow_call(operation, prefix + content).find('return')
                if result is not None and result.get('serviceName'):
                    params = {entry.findtext('key'): entry.findtext('value')
                              for entry in result.findall('serviceParams/entries')}
                    if not (operation == 'startCommand' and result.get('serviceName') == 'MESSAGE'
                            and params.get('commandId') == '3007' and params.get('messageType') in ('2', '6')):
                        raise ValueError('Der Server hat das Löschen der Bezüge nicht bestätigt.')
                context = result.find('changedSessionContext') if result is not None else None
                if context is not None:
                    if context.findall('simpleAttributes'):
                        state['attributes'] = parse_property_context(context)
                    # startCommand may return the unchanged list with its confirmation.
                    changed_references = context.find("complexAttributes[@identifier='bezuege']")
                    if operation == 'endCommand' and changed_references is not None:
                        state['references'] = parse_reference_rows(changed_references)
            return state

    def open_workflow_templates(self, object_id, object_kind, state=None):
        with self._lock:
            if state is None:
                context = self.workflow_call('createGetBoSession',
                    f'<obj_id xmlns="">{int(object_id)}</obj_id><obj_typ xmlns="">{int(object_kind)}</obj_typ>').find('return')
                if context is None or not context.get('instanceId'):
                    raise ValueError('Keine Objektsitzung vorhanden.')
                state = {'session_id': context.get('instanceId'), 'attributes': parse_property_context(context),
                         'tasks': self.workflow_rows(context), 'reminders': self.reminder_rows(context)}
            result = self.workflow_call('startCommand',
                f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><commandid xmlns="">3028</commandid>'
                '<changedAttributes xmlns=""/><param xmlns=""><version>0</version></param>').find('return')
            if result is None or result.get('serviceName') != 'GGVMUSTERVERWALTUNG' or result.find('serviceParams') is None:
                raise ValueError('Der Server hat keine Geschäftsgangmusterauswahl geliefert.')
            params = result.find('serviceParams')
            context = self.workflow_call('createServiceSession',
                '<serviceName xmlns="">GGVMUSTERVERWALTUNG</serviceName>' + self.workflow_params(params)).find('return')
            if context is None or not context.get('instanceId'):
                raise ValueError('Keine Sitzung für die Geschäftsgangmusterauswahl vorhanden.')
            session = context.get('instanceId')
            try:
                prefix = f'<sessionid xmlns="">{escape(session)}</sessionid>'
                self.workflow_call('getComplexAttributes', prefix + '<identifiers xmlns="">iter@trefferliste</identifiers>')
                collection = self.workflow_call('getComplexAttribute', prefix + '<identifier xmlns="">iter@trefferliste</identifier>').find('return')
                if collection is None:
                    raise ValueError('Der Server hat keine Musterliste geliefert.')
                rows = [dict({col.get('identifier'): col.findtext('value') or '' for col in row.findall('columns')},
                             _session_index=int(row.get('index'))) for row in collection.findall('rows')]
                return {'session_id': session, 'params': XML.tostring(params, encoding='unicode'),
                        'rows': rows, 'state': dict(state)}
            except Exception:
                self.cancel_workflow_template({'session_id': session, 'state': state})
                raise

    def apply_workflow_template(self, editor, index):
        with self._lock:
            index = int(index)
            if index not in [row['_session_index'] for row in editor['rows']]:
                raise ValueError('Das Geschäftsgangmuster ist nicht mehr vorhanden.')
            selection = f'''<complexAttributes behavior="0" identifier="iter@trefferliste">
<rows focused="false" selected="true" style="0" styleColor="0" visible="false" index="{index}" dragDropDataObjId="0" dragDropTyp="0" uniqueId="0">
<columns identifier="__select" idvalue="0" maxLength="0" behavior="0"><value>1</value>
<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode><changeTyp>3</changeTyp>
<master>false</master><slave>false</slave></columns></rows></complexAttributes>'''
            prefix = f'<sessionid xmlns="">{escape(editor["session_id"])}</sessionid><commandid xmlns="">200404</commandid>'
            state = dict(editor['state'])
            for operation, content in (
                ('startCommand', f'<changedAttributes xmlns="">{selection}</changedAttributes>' + self.workflow_params(XML.fromstring(editor['params']), 'param')),
                ('endCommand', '<serviceParams xmlns=""><entries><key xsi:type="xsd:string">SERVICE_END_COMMAND</key><value xsi:type="xsd:int">200404</value></entries><version>0</version></serviceParams>'),
                ('endCommand', None)):
                if content is None:
                    prefix = f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><commandid xmlns="">3028</commandid>'
                    params = result.find('serviceParams') if result is not None else None
                    content = self.workflow_params(params) if params is not None else '<serviceParams xmlns=""><version>0</version></serviceParams>'
                result = self.workflow_call(operation, prefix + content).find('return')
                if result is not None and result.get('serviceName'):
                    raise ValueError('Der Server hat das Geschäftsgangmuster nicht übernommen.')
                context = result.find('changedSessionContext') if result is not None else None
                if context is not None and context.get('instanceId') in (None, state['session_id']):
                    if context.findall('simpleAttributes'):
                        state['attributes'] = parse_property_context(context)
                    if context.find("complexAttributes[@identifier='ggvermerke']") is not None:
                        state['tasks'] = self.workflow_rows(context)
                    if context.find("complexAttributes[@identifier='wiedervorlagen']") is not None:
                        state['reminders'] = self.reminder_rows(context)
            state['workflow'] = True
            return state

    def cancel_workflow_template(self, editor):
        with self._lock:
            result = self.workflow_call('endCommand',
                f'<sessionid xmlns="">{escape(editor["session_id"])}</sessionid><commandid xmlns="">1003</commandid>'
                '<serviceParams xmlns=""><entries><key xsi:type="xsd:string">SERVICE_END_COMMAND</key>'
                '<value xsi:type="xsd:int">1003</value></entries><version>0</version></serviceParams>').find('return')
            params = result.find('serviceParams') if result is not None else None
            self.workflow_call('endCommand',
                f'<sessionid xmlns="">{escape(editor["state"]["session_id"])}</sessionid><commandid xmlns="">3028</commandid>'
                + (self.workflow_params(params) if params is not None else '<serviceParams xmlns=""><version>0</version></serviceParams>'))

    def prepare_existing_task_edit(self, object_id, object_kind, state, task_id):
        with self._lock:
            editing = self.begin_property_edit(object_id, object_kind) if state is None else state
            task = next((task for task in editing.get('tasks', [])
                         if task.get('ggv_id') == str(task_id)), None)
            if task is None or task.get('erledigt_am'):
                if state is None:
                    self.cancel_property_edit(editing['session_id'])
                raise ValueError('Die Geschäftsgangverfügung ist nicht mehr offen oder vorhanden.')
            return {'state': editing, 'index': task['_session_index']}

    def open_workflow_task(self, state, index):
        with self._lock:
            session = escape(state['session_id'])
            index = int(index)
            indices = [int(task['_session_index']) for task in state['tasks']]
            if index not in indices:
                raise ValueError('Die Geschäftsgangverfügung ist nicht mehr vorhanden.')
            if any(int(task['_session_index']) == index and task.get('erledigt_am') for task in state['tasks']):
                raise ValueError('Erledigte Geschäftsgangverfügungen können nicht bearbeitet werden.')
            rows = ''.join(f'''<rows focused="false" selected="{str(row == index).lower()}" style="0" styleColor="0"
visible="false" index="{row}" dragDropDataObjId="0" dragDropTyp="0" uniqueId="0">
<columns identifier="__select" idvalue="0" maxLength="0" behavior="0"><value>{int(row == index)}</value>
<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode><changeTyp>3</changeTyp>
<master>false</master><slave>false</slave></columns></rows>''' for row in indices)
            selection = f'<complexAttributes behavior="0" identifier="ggvermerke">{rows}</complexAttributes>'
            result = self.workflow_call('startCommand', f'''<sessionid xmlns="">{session}</sessionid><commandid xmlns="">6154</commandid>
<changedAttributes xmlns="">{selection}</changedAttributes><param xmlns=""><version>0</version></param>''').find('return')
            if result is None or result.get('serviceName') != 'GGVEDIT' or result.find('serviceParams') is None:
                raise ValueError('Der Server hat keinen Geschäftsgangeditor geliefert.')
            params = result.find('serviceParams')
            context = self.workflow_call('createServiceSession', '<serviceName xmlns="">GGVEDIT</serviceName>'
                                         + self.workflow_params(params)).find('return')
            if context is None or not context.get('instanceId'):
                raise ValueError('Keine Sitzung für den Geschäftsgangeditor vorhanden.')
            editor_session = context.get('instanceId')
            prefix = f'<sessionid xmlns="">{escape(editor_session)}</sessionid>'
            combos = self.workflow_call('getComboList', prefix + '<attrId xmlns="">erledigung</attrId>')
            for combo in combos.findall('return'):
                combo.tag = 'comboList'
                context.append(combo)
            combos = self.workflow_call('getComboLists', prefix + ''.join(
                f'<attrIds xmlns="">{key}</attrIds>' for key in ('kategorie', 'kategorie_typ', 'aufgabe', 'erledigung', 'pkg_kategorie')))
            for combo in combos.findall('return'):
                combo.tag = 'comboList'
                context.append(combo)
            attributes = parse_property_context(context)
            for attr, node in zip(attributes, context.findall('simpleAttributes')):
                attr['idvalue'] = node.get('idvalue', '0')
            return {'session_id': editor_session, 'params': XML.tostring(params, encoding='unicode'),
                    'attributes': attributes, 'index': index}

    def apply_workflow_task(self, editor, changes):
        with self._lock:
            attributes = ''
            for key, change in changes.items():
                value, idvalue = change
                value_xml = '' if key == 'kategorie' else f'<value>{escape(value)}</value>'
                change_type = 2 if key == 'kategorie' else 3
                attributes += f'''<simpleAttributes identifier={quoteattr(key)} idvalue="{int(idvalue)}" maxLength="0" behavior="0">
{value_xml}<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode>
<changeTyp>{change_type}</changeTyp><master>false</master><slave>false</slave></simpleAttributes>'''
            prefix = f'<sessionid xmlns="">{escape(editor["session_id"])}</sessionid><commandid xmlns="">1001</commandid>'
            result = self.workflow_call('startCommand', prefix + f'<changedAttributes xmlns="">{attributes}</changedAttributes>'
                + self.workflow_params(XML.fromstring(editor['params']), 'param')).find('return')
            if result is not None and result.get('serviceName'):
                raise ValueError('Der Server hat die Eingaben nicht akzeptiert.')
            result = self.workflow_call('endCommand', prefix + '''<serviceParams xmlns=""><entries>
<key xsi:type="xsd:string">SERVICE_END_COMMAND</key><value xsi:type="xsd:int">1001</value>
</entries><version>0</version></serviceParams>''').find('return')
            if result is not None and result.get('serviceName'):
                raise ValueError('Der Server hat die Übernahme nicht bestätigt.')
            return changes

    def cancel_workflow_editor(self, editor):
        self.workflow_call('cancel', f'<sessionid xmlns="">{escape(editor["session_id"])}</sessionid>')

    def begin_property_edit(self, object_id, object_kind):
        with self._lock:
            payload = f'''<s:Envelope xmlns:s="{SOAP}"><s:Body><createGetBoSession xmlns="{SERVICE}">
<obj_id xmlns="">{int(object_id)}</obj_id><obj_typ xmlns="">{int(object_kind)}</obj_typ>
</createGetBoSession></s:Body></s:Envelope>'''.encode()
            body = parse_soap_body(self.soap_request('SessionObject', payload))
            context = body.find(f'{{{SERVICE}}}createGetBoSessionResponse/return')
            if context is None or not context.get('instanceId'):
                raise ValueError('Keine Objektsitzung zum Bearbeiten vorhanden.')
            session = context.get('instanceId')
            collection = next((e.findtext('value') for e in context.findall('serviceParams/entries')
                               if e.findtext('key') == 'bo.update.ignore.collection'), None)
            self.property_command(session, 1037, collection=collection)
            result = self.property_command(session, 1037, 'endCommand')
            changed = result.find('changedSessionContext') if result is not None else None
            if changed is None:
                self.cancel_property_edit(session)
                raise ValueError('Der Server hat keine bearbeitbaren Eigenschaften geliefert.')
            # The edit context only carries each combo's current value; fetch the selectable items.
            combo_ids = [attribute.get('identifier') for attribute in changed.findall('simpleAttributes')
                         if attribute.findtext('drawType') in ('3', '4') and attribute.get('identifier')]
            if combo_ids:
                try:
                    combos = self.workflow_call('getComboLists', f'<sessionid xmlns="">{escape(session)}</sessionid>'
                                                + ''.join(f'<attrIds xmlns="">{escape(key)}</attrIds>' for key in combo_ids))
                except Exception:
                    self.cancel_property_edit(session)
                    raise
                for combo in combos.findall('return'):
                    combo.tag = 'comboList'
                    changed.append(combo)
            return {'session_id': session, 'attributes': parse_property_context(changed),
                    'tasks': self.workflow_rows(changed if changed.find("complexAttributes[@identifier='ggvermerke']") is not None else context),
                    'reminders': self.reminder_rows(changed if changed.find("complexAttributes[@identifier='wiedervorlagen']") is not None else context)}

    def fetch_user_tree(self, session_id, tree_name):
        result = self.workflow_call('getTreeData',
            f'<sessionId xmlns="">{escape(session_id)}</sessionId>'
            f'<treeName xmlns="">{escape(tree_name)}</treeName>').find('return')
        if result is None or not result.findtext('instanceId'):
            raise ValueError('Die Sitzung enthält keinen Nutzerbaum. Die Nutzerauswahl muss zuerst als eigene Serversitzung geöffnet werden.')
        return {'session_id': result.findtext('instanceId'),
                'id': result.findtext('id') or '0',
                'name': result.findtext('rootName') or 'Aufbauorganisation'}

    def fetch_user_tree_children(self, session_id, node_id):
        response = self.workflow_call('getFlatTreeItemList',
            f'<sessionId xmlns="">{escape(session_id)}</sessionId>'
            f'<id xmlns="">{escape(node_id)}</id><force xmlns="">false</force>')
        nodes = []
        for item in response.findall('return'):
            identifier = item.get('dataBaseId', '').rsplit('/', 1)[-1].strip('()')
            has_children = item.get('hasChildren') == 'true'
            try:
                nodes.append({'id': item.get('id'),
                          'selected_value': item.get('selectedValue') or item.get('dataBaseId'),
                          'name': item.findtext('text') or '',
                          'has_children': has_children,
                          'user_id': int(identifier) if (not has_children) else None})
            except ValueError: pass
        return nodes

    def _open_object_task_editor(self, object_id, object_kind, task_id):
        response = self.workflow_call('createGetBoSession',
            f'<obj_id xmlns="">{int(object_id)}</obj_id>'
            f'<obj_typ xmlns="">{int(object_kind)}</obj_typ>')
        context = response.find('return')
        if context is None or not context.get('instanceId'):
            raise ValueError('Keine Objektsitzung vorhanden.')
        tasks = self.workflow_rows(context)
        task = next((task for task in tasks if task.get('ggv_id') == str(task_id)), None)
        if task is None:
            raise ValueError('Die Aufgabe ist nicht mehr vorhanden.')
        return self.open_workflow_task(
            {'session_id': context.get('instanceId'), 'tasks': tasks}, task['_session_index'])

    def open_stellvertreter_management(self):
        tenant = unquote(urlsplit(self.server_url).path.rstrip('/').rsplit('/', 1)[-1])
        tenant = '{' + tenant.strip('{}') + '}'
        with self._lock:
            context = self.workflow_call('createServiceSession',
                '<serviceName xmlns="">STELLVERTRETUNGADMINISTRATION</serviceName><serviceParams xmlns="">'
                '<entries><key xsi:type="xsd:string">PARAM_ADD_COMPLEX_ATTR</key><value xsi:type="q1:xList">'
                '<entries xsi:type="xsd:string">tableStellvertreter</entries><version>1</version></value></entries>'
                f'<entries><key xsi:type="xsd:string">mandant</key><value xsi:type="xsd:string">{escape(tenant)}</value></entries>'
                '<version>0</version></serviceParams>').find('return')
            if context is None or not context.get('instanceId'):
                raise ValueError('Der Server hat keine Stellvertreterverwaltung geliefert.')
            state = {'session_id': context.get('instanceId')}
            try:
                return self.reload_stellvertreter_management(state)
            except Exception:
                self.close_user_selection(state['session_id'])
                raise

    def reload_stellvertreter_management(self, state):
        with self._lock:
            collection = self.workflow_call('getComplexAttribute',
                f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid>'
                '<identifier xmlns="">tableStellvertreter</identifier>').find('return')
            if collection is None:
                raise ValueError('Der Server hat keine Stellvertreterliste geliefert.')
            rows = [dict({col.get('identifier'): col.findtext('value') or '' for col in row.findall('columns')},
                         _session_index=row.get('index')) for row in collection.findall('rows')]
            return dict(state, rows=rows)

    def delete_stellvertreter(self, state, index):
        with self._lock:
            index = int(index)
            if index < 0 or not any(str(row['_session_index']) == str(index) for row in state['rows']):
                raise ValueError('Der Stellvertreter ist nicht mehr vorhanden.')
            prefix = f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><commandid xmlns="">205001</commandid>'
            selection = f'''<complexAttributes behavior="0" identifier="tableStellvertreter">
<rows focused="false" selected="true" style="0" styleColor="0" visible="false" index="{index}" dragDropDataObjId="0" dragDropTyp="0" uniqueId="0">
<columns identifier="__select" idvalue="0" maxLength="0" behavior="0"><value>1</value>
<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode><changeTyp>3</changeTyp>
<master>false</master><slave>false</slave></columns></rows></complexAttributes>'''
            for operation, content in (
                ('startCommand', f'<changedAttributes xmlns="">{selection}</changedAttributes><param xmlns=""><version>0</version></param>'),
                ('endCommand', '<serviceParams xmlns=""><version>0</version></serviceParams>')):
                result = self.workflow_call(operation, prefix + content).find('return')
                if result is not None and result.get('serviceName'):
                    raise ValueError('Der Server hat das Löschen nicht bestätigt.')
            prefix = f'<sessionid xmlns="">{escape(state["session_id"])}</sessionid><commandid xmlns="">1002</commandid>'
            for operation, content in (
                ('startCommand', '<changedAttributes xmlns=""/><param xmlns=""><version>0</version></param>'),
                ('endCommand', '<serviceParams xmlns=""><version>0</version></serviceParams>')):
                result = self.workflow_call(operation, prefix + content).find('return')
                if result is not None and result.get('serviceName'):
                    raise ValueError('Der Server hat die Stellvertreteränderung nicht gespeichert.')
            self.fetch_stellvertreter()
            return self.reload_stellvertreter_management(state)

    def open_stellvertreter_selection(self, management_session):
        with self._lock:
            result = self.workflow_call('startCommand',
                f'<sessionid xmlns="">{escape(management_session)}</sessionid><commandid xmlns="">205000</commandid>'
                '<changedAttributes xmlns=""/><param xmlns=""><version>0</version></param>').find('return')
            if result is None or result.get('serviceName') != 'NUTZERAUSWAHL' or result.find('serviceParams') is None:
                raise ValueError('Der Server hat keine Nutzerauswahl geliefert.')
            params = result.find('serviceParams')
            context = self.workflow_call('createServiceSession',
                '<serviceName xmlns="">NUTZERAUSWAHL</serviceName>' + self.workflow_params(params)).find('return')
            if context is None or not context.get('instanceId'):
                raise ValueError('Der Server hat keine Nutzerauswahl-Sitzung geliefert.')
            session = context.get('instanceId')
            try:
                root = self.fetch_user_tree(session, 'tree')
            except Exception:
                self.close_user_selection(session)
                raise
            root.update(selection_session=session, management_session=management_session,
                        selection_params=XML.tostring(params, encoding='unicode'))
            return root

    def confirm_stellvertreter_selection(self, selection, tree_path):
        with self._lock:
            prefix = f'<sessionid xmlns="">{escape(selection["selection_session"])}</sessionid>'
            tree = f'''<simpleAttributes identifier="tree" idvalue="0" maxLength="0" behavior="0">
<value>{escape(tree_path)}</value><attributeType>0</attributeType><drawType>0</drawType>
<comcode>0</comcode><changeTyp>3</changeTyp><master>false</master><slave>false</slave></simpleAttributes>'''
            for operation, command, content in (
                ('startCommand', 202705, f'<changedAttributes xmlns="">{tree}</changedAttributes><param xmlns=""><version>0</version></param>'),
                ('endCommand', 202705, '<serviceParams xmlns=""><version>0</version></serviceParams>'),
                ('startCommand', 1001, '<changedAttributes xmlns=""/>' + self.workflow_params(XML.fromstring(selection['selection_params']), 'param')),
                ('endCommand', 1001, '<serviceParams xmlns=""><entries><key xsi:type="xsd:string">SERVICE_END_COMMAND</key><value xsi:type="xsd:int">1001</value></entries><version>0</version></serviceParams>')):
                result = self.workflow_call(operation, prefix + f'<commandid xmlns="">{command}</commandid>' + content).find('return')
                if result is not None and result.get('serviceName'):
                    raise ValueError('Der Server hat die Nutzerauswahl nicht bestätigt.')
            params = result.find('serviceParams') if result is not None else None
            if params is None or params.find("entries[key='userList']") is None:
                raise ValueError('Der Server hat keine ausgewählten Nutzer geliefert.')
            result = self.workflow_call('endCommand',
                f'<sessionid xmlns="">{escape(selection["management_session"])}</sessionid><commandid xmlns="">205000</commandid>'
                + self.workflow_params(params)).find('return')
            if result is not None and result.get('serviceName'):
                raise ValueError('Der Server hat den Stellvertreter nicht übernommen.')
            prefix = f'<sessionid xmlns="">{escape(selection["management_session"])}</sessionid><commandid xmlns="">1002</commandid>'
            for operation, content in (
                ('startCommand', '<changedAttributes xmlns=""/><param xmlns=""><version>0</version></param>'),
                ('endCommand', '<serviceParams xmlns=""><version>0</version></serviceParams>')):
                result = self.workflow_call(operation, prefix + content).find('return')
                if result is not None and result.get('serviceName'):
                    raise ValueError('Der Server hat die Stellvertreteränderung nicht gespeichert.')
            self.fetch_stellvertreter()
            return result

    def open_user_selection(self):
        """Create the dedicated NUTZERAUSWAHL session before requesting its tree."""
        tenant = unquote(urlsplit(self.server_url).path.rstrip('/').rsplit('/', 1)[-1])
        if not tenant:
            raise ValueError('Die Server-URL enthält keinen Mandanten.')
        tenant = '{' + tenant.strip('{}') + '}'
        with self._lock:
            result = self.workflow_call('createServiceSession',
                '<serviceName xmlns="">NUTZERAUSWAHL</serviceName><serviceParams xmlns="">'
                '<entries><key xsi:type="xsd:string">mode</key><value xsi:type="xsd:int">299</value></entries>'
                '<entries><key xsi:type="xsd:string">options</key><value xsi:type="xsd:int">1610612800</value></entries>'
                '<entries><key xsi:type="xsd:string">artFilter</key><value xsi:type="q1:xList">'
                '<entries xsi:type="xsd:int">1</entries><entries xsi:type="xsd:int">2</entries>'
                '<entries xsi:type="xsd:int">3</entries><version>1</version></value></entries>'
                '<entries><key xsi:type="xsd:string">artAuswahlBlacklist</key></entries>'
                f'<entries><key xsi:type="xsd:string">mandant</key><value xsi:type="xsd:string">{escape(tenant)}</value></entries>'
                '<version>0</version></serviceParams>').find('return')
            if result is None or not result.get('instanceId'):
                raise ValueError('Der Server hat keine Nutzerauswahl-Sitzung geliefert.')
            session = result.get('instanceId')
            try:
                root = self.fetch_user_tree(session, 'tree')
            except Exception:
                self.close_user_selection(session)
                raise
            root['selection_session'] = session
            return root

    def close_user_selection(self, session_id):
        self.workflow_call('cancel', f'<sessionid xmlns="">{escape(session_id)}</sessionid>')

    def fetch_task_categories(self, object_kind, task):
        """Query categories for the type supplied by the existing task row."""
        try:
            category_type = int(task['_category_ids']['kategorie_typ'])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Die Aufgabe enthält keinen gültigen Kategorietyp.') from error
        object_kind = int(object_kind)
        endpoint = self.server_url + '/vistree/GGKategories()'
        url = endpoint + '?' + urlencode({
            '$filter': f'KategorieTyp eq {category_type}L and ObjektartId eq {object_kind}L',
            '$orderby': 'Reihenfolge'}, quote_via=quote, safe='$,()')
        choices = {}
        with self._lock:
            for payload in self.feed_pages(url, endpoint):
                rows, _count, _more = parse_tree_page(payload)
                for row in rows:
                    if int(row['KategorieTyp']) != category_type or int(row['ObjektartId']) != object_kind:
                        continue
                    choices[row['Name']] = str(int(row['KategorieId']))
        return {'identifier': 'kategorie', 'value': task.get('kategorie', ''),
                'idvalue': task.get('_category_ids', {}).get('kategorie'),
                'choices': list(choices), 'choice_ids': choices}

    def reject_object_task(self, object_id, object_kind, task_id, note):
        return self.complete_object_task(object_id, object_kind, task_id, note, reject=True)

    def redirect_object_task(self, object_id, object_kind, task_id, note, redirect):
        if int(redirect['recipient_id']) <= 0 or not redirect['recipient_name'].strip():
            raise ValueError('Bitte einen Empfänger auswählen.')
        return self.complete_object_task(object_id, object_kind, task_id, note, redirect=redirect)

    def complete_object_task(self, object_id, object_kind, task_id, note, reject=False, redirect=None):
        command_id = 30051 if redirect is not None else 30052 if reject else 3005
        with self._lock:
            response = self.workflow_call('createGetBoSession',
                f'<obj_id xmlns="">{int(object_id)}</obj_id>'
                f'<obj_typ xmlns="">{int(object_kind)}</obj_typ>')
            context = response.find('return')
            if context is None or not context.get('instanceId'):
                raise ValueError('Keine Objektsitzung zum Erledigen vorhanden.')
            tasks = self.workflow_rows(context)
            selected = [task for task in tasks if task.get('ggv_id') == str(task_id)]
            if (len(selected) != 1 or not self.user_id
                    or selected[0].get('_assignee_id') != str(self.user_id)
                    or selected[0].get('erledigt_am')):
                raise ValueError('Die Aufgabe ist nicht mehr offen oder Ihnen nicht zugewiesen.')
            rows = []
            for task in tasks:
                active = task is selected[0]
                # Reject/redirect change only the selected row, as in the VIS requests.
                if not active and (reject or redirect is not None):
                    continue
                columns = [('erledigung', note), ('__select', '1')] if active else [('__select', '0')]
                if redirect is not None and active and not note:
                    columns = [('__select', '1')]
                fields = ''.join(f'<columns identifier={quoteattr(key)} idvalue="0" maxLength="0" behavior="0">'
                    f'<value>{escape(value)}</value><attributeType>0</attributeType><drawType>0</drawType>'
                    '<comcode>0</comcode><changeTyp>3</changeTyp><master>false</master><slave>false</slave></columns>'
                    for key, value in columns)
                rows.append(f'<rows focused="false" selected="{str(active).lower()}" style="0" styleColor="0" '
                    f'visible="false" index="{int(task["_session_index"])}" dragDropDataObjId="0" '
                    f'dragDropTyp="0" uniqueId="0">{fields}</rows>')
            session = context.get('instanceId')
            prefix = f'<sessionid xmlns="">{escape(session)}</sessionid><commandid xmlns="">{command_id}</commandid>'
            extra_params = ''
            if redirect is not None:
                recipient = str(int(redirect['recipient_id']))
                name = redirect['recipient_name'].strip()
                params = [('erlassen_fuer_id', 'int', recipient), ('erlassen_fuer', 'string', name),
                          ('kategorie', 'string', str(int(redirect['category']))),
                          ('pkg_kategorie', 'string', selected[0]['_category_ids'].get('pkg_kategorie') or '-11008'),
                          ('ggv_multi_receivers', 'string', f'--;{recipient};{name};'),
                          ('aufgabe', 'string', redirect['task']), ('termin', 'string', redirect['due']),
                          ('Geschaeftsgang.QUELLE_ERLEDIGEN', 'boolean', 'true')]
                extra_params = ''.join(f'<entries><key xsi:type="xsd:string">{escape(key)}</key>'
                    f'<value xsi:type="xsd:{kind}">{escape(value)}</value></entries>' for key, kind, value in params)
            result = self.workflow_call('startCommand', prefix +
                '<changedAttributes xmlns=""><complexAttributes behavior="0" identifier="ggvermerke">'
                + ''.join(rows) + '</complexAttributes></changedAttributes><param xmlns="">' + extra_params + '<entries>'
                '<key xsi:type="xsd:string">de.pdv.visj.business.rule.Commands.APPLY_AFTER_COMMAND_ID</key>'
                f'<value xsi:type="xsd:int">{command_id}</value></entries><version>0</version></param>').find('return')
            if result is not None and result.get('serviceName'):
                raise ValueError('Der Server hat das Erledigen nicht bestätigt.')
            self.property_command(session, command_id, 'endCommand')
            self.property_command(session, 1002)
            self.property_command(session, 1002, 'endCommand')

    def unlock_object(self, object_id, object_kind):
        """Release the selected object's lock using VIS command 6146."""
        with self._lock:
            response = self.workflow_call('createGetBoSession',
                f'<obj_id xmlns="">{int(object_id)}</obj_id>'
                f'<obj_typ xmlns="">{int(object_kind)}</obj_typ>')
            context = response.find('return')
            if context is None or not context.get('instanceId'):
                raise ValueError('Keine Objektsitzung zum Entsperren vorhanden.')
            session = context.get('instanceId')
            self.property_command(session, 6146, changes={'auslauf': ''})
            self.property_command(session, 6146, 'endCommand')

    def cancel_property_edit(self, session_id):
        with self._lock:
            result = self.property_command(session_id, 1003, allow_cancel_prompt=True)
            answer = None
            if result is not None and result.get('serviceName') == 'MESSAGE':
                # Abbrechen discards edits; answer No to the server's save prompt.
                answer = 2
            self.property_command(session_id, 1003, 'endCommand', message_return=answer)

    def property_command(self, session_id, command_id, operation='startCommand', changes=None, collection=None,
                         allow_cancel_prompt=False, message_return=None):
        """Send one properties command and reject server dialogs or SOAP faults."""
        attributes = ''
        for identifier, value in (changes or {}).items():
            attributes += f'''<simpleAttributes identifier={quoteattr(identifier)} idvalue="0" maxLength="0" behavior="0">
<value>{escape(str(value))}</value><attributeType>0</attributeType><drawType>0</drawType>
<comcode>0</comcode><changeTyp>3</changeTyp><master>false</master><slave>false</slave></simpleAttributes>'''
        if operation == 'startCommand':
            params = '' if collection is None else f'''<entries><key xsi:type="xsd:string">bo.update.ignore.collection</key>
<value xsi:type="xsd:string">{escape(collection)}</value></entries>'''
            content = f'<changedAttributes xmlns="">{attributes}</changedAttributes><param xmlns="">{params}<version>0</version></param>'
        else:
            answer = '' if message_return is None else f'''<entries><key xsi:type="xsd:string">messagereturn</key>
<value xsi:type="xsd:byte">{int(message_return)}</value></entries>'''
            content = f'<serviceParams xmlns="">{answer}<version>0</version></serviceParams>'
        payload = f'''<s:Envelope xmlns:s="{SOAP}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
xmlns:xsd="http://www.w3.org/2001/XMLSchema"><s:Body><{operation} xmlns="{SERVICE}">
<sessionid xmlns="">{escape(session_id)}</sessionid><commandid xmlns="">{int(command_id)}</commandid>
{content}</{operation}></s:Body></s:Envelope>'''.encode()
        body = parse_soap_body(self.soap_request('SessionObject', payload))
        response = body.find(f'{{{SERVICE}}}{operation}Response')
        if response is None:
            raise ValueError('Der Server hat den Eigenschaften-Befehl nicht bestätigt.')
        result = response.find('return')
        if result is not None and result.get('serviceName'):
            params = {entry.findtext('key'): entry.findtext('value')
                      for entry in result.findall('serviceParams/entries')}
            cancel_prompt = (allow_cancel_prompt and operation == 'startCommand' and command_id == 1003
                             and result.get('serviceName') == 'MESSAGE'
                             and params.get('commandId') == '1003'
                             and params.get('messageType') == '6'
                             and (params.get('message') or '').strip() == 'Möchten Sie die Änderungen speichern?')
            if not cancel_prompt:
                raise ValueError('Der Server meldet eine Rückfrage oder einen Validierungsfehler.')
        return result

    def save_properties(self, session_id, changes):
        with self._lock:
            for command in (1002, 1007):
                self.property_command(session_id, command, changes=changes if command == 1002 else None)
                self.property_command(session_id, command, 'endCommand')

    def rename_file(self, object_kind, file, name):
        """Rename through the server's BEARBEITEN validation session."""
        if (not name.strip() or name.startswith('.') or name.endswith('.') or '..' in name
                or any(char in name for char in '\\/:;*?"<>|&~#%{}+\t\r\n\0')):
            raise ValueError('Bitte einen gültigen Dateinamen ohne Erweiterung eingeben.')

        def call(operation, content):
            payload = f'''<s:Envelope xmlns:s="{SOAP}" xmlns:ns2="{SERVICE}"
xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsd="http://www.w3.org/2001/XMLSchema"
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><s:Body>
<{operation} xmlns="{SERVICE}">{content}</{operation}></s:Body></s:Envelope>'''
            body = parse_soap_body(self.soap_request('SessionObject', payload.encode()))
            response = body.find(f'{{{SERVICE}}}{operation}Response')
            if response is None:
                raise ValueError('Ungültige Serverantwort beim Umbenennen.')
            return response.find('return')

        def params_xml(params, tag='serviceParams'):
            params = XML.fromstring(XML.tostring(params))
            params.tag = tag
            params.set('xmlns', '')
            version = params.find('version')
            if version is not None:
                version.text = '0'
            return XML.tostring(params, encoding='unicode')

        def command(session, number):
            return f'<sessionid xmlns="">{escape(session)}</sessionid><commandid xmlns="">{number}</commandid>'

        with self._lock:
            context = call('createGetBoSession', f'<obj_id xmlns="">{file.bo_id}</obj_id><obj_typ xmlns="">{int(object_kind)}</obj_typ>')
            if context is None or not context.get('instanceId'):
                raise ValueError('Keine Objektsitzung zum Umbenennen vorhanden.')
            session = context.get('instanceId')
            rows = context.findall("complexAttributes[@identifier='dokinhaltselemente']/rows")
            matches = [row for row in rows if row.findtext("columns[@identifier='id']/value") == str(file.file_id)]
            if len(matches) != 1 or int(matches[0].get('index', '-1')) < 0:
                raise ValueError('Datei nicht mehr eindeutig vorhanden. Bitte neu laden.')
            selection = ''.join(f'''<rows index="{int(row.get('index'))}" selected="{'true' if row is matches[0] else 'false'}">
<columns identifier="__select"><value>{1 if row is matches[0] else 0}</value><changeTyp>3</changeTyp></columns></rows>''' for row in rows)
            result = call('startCommand', command(session, 5020) + f'''<changedAttributes xmlns="">
<complexAttributes identifier="dokinhaltselemente" behavior="0">{selection}</complexAttributes>
</changedAttributes><param xmlns=""><version>0</version></param>''')
            if result is None or result.get('serviceName') != 'BEARBEITEN':
                raise ValueError('Der Server hat keinen Umbenennungsdialog geliefert.')
            params = result.find('serviceParams')
            if params is None:
                raise ValueError('Parameter für die Umbenennung fehlen.')
            values = {e.findtext('key'): e.findtext('value') for e in params.findall('entries')}
            if values.get('bearbeitenvalue') != file.name or values.get('withExtension') != 'false':
                raise ValueError('Der Umbenennungsdialog passt nicht zur ausgewählten Datei.')
            edit = call('createServiceSession', '<serviceName xmlns="">BEARBEITEN</serviceName>' + params_xml(params))
            if edit is None or not edit.get('instanceId'):
                raise ValueError('Keine Bearbeitungssitzung vorhanden.')
            edit_session = edit.get('instanceId')
            try:
                result = call('startCommand', command(edit_session, 1001) + f'''<changedAttributes xmlns="">
<simpleAttributes identifier="eingabe" idvalue="0" maxLength="0" behavior="0"><value>{escape(name)}</value>
<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode><changeTyp>3</changeTyp>
<master>false</master><slave>false</slave></simpleAttributes></changedAttributes>''' + params_xml(params, 'param'))
                if result is None or result.get('serviceName'):
                    raise ValueError('Der Server hat den neuen Dateinamen nicht akzeptiert.')
                result = call('endCommand', command(edit_session, 1001) + '''<serviceParams xmlns=""><entries>
<key xsi:type="xsd:string">SERVICE_END_COMMAND</key><value xsi:type="xsd:int">1001</value>
</entries><version>0</version></serviceParams>''')
                returned = result.find('serviceParams') if result is not None else None
                values = {e.findtext('key'): e.findtext('value') for e in returned.findall('entries')} if returned is not None else {}
                if values.get('bearbeitenreturn') != 'TRUE' or values.get('bearbeitenvalue') != name + Path(file.name).suffix:
                    raise ValueError('Der Server hat den gewünschten Dateinamen nicht bestätigt.')
            finally:
                call('cancel', f'<sessionid xmlns="">{escape(edit_session)}</sessionid>')
            result = call('endCommand', command(session, 5020) + params_xml(returned))
            if result is None or result.get('serviceName'):
                raise ValueError('Der Server hat die Umbenennung nicht bestätigt.')

    def prepare_file_deletion(self, object_id, object_kind, files):
        """Resolve stable file IDs to fresh session row indexes and request confirmation."""
        object_id = int(object_id)
        if not files or any(file.bo_id != object_id for file in files):
            raise ValueError('Die Dateien gehören nicht zum ausgewählten Objekt.')
        with self._lock:
            payload = f'''<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>
<createGetBoSession xmlns="{SERVICE}"><obj_id xmlns="">{object_id}</obj_id>
<obj_typ xmlns="">{int(object_kind)}</obj_typ></createGetBoSession></soap:Body></soap:Envelope>'''
            body = parse_soap_body(self.soap_request('SessionObject', payload.encode('utf-8')))
            context = body.find(f'{{{SERVICE}}}createGetBoSessionResponse/return')
            session_id = context.get('instanceId') if context is not None else None
            if not session_id:
                raise ValueError('SOAP-Antwort enthält keine Objektsitzung.')
            rows = context.findall("complexAttributes[@identifier='dokinhaltselemente']/rows")
            indexes = []
            for file in files:
                matches = [row for row in rows if row.findtext("columns[@identifier='id']/value") == str(file.file_id)]
                if len(matches) != 1:
                    raise ValueError('Die Dateiliste hat sich geändert. Bitte neu laden und erneut versuchen.')
                index = int(matches[0].get('index', '-1'))
                if index < 0 or index in indexes:
                    raise ValueError('Ungültiger Dateiindex in der Objektsitzung.')
                indexes.append(index)
            selection = ''.join(f'''<rows focused="false" selected="true" style="0" styleColor="0"
visible="false" index="{index}" dragDropDataObjId="0" dragDropTyp="0" uniqueId="0">
<columns identifier="__select" idvalue="0" maxLength="0" behavior="0"><value>1</value>
<attributeType>0</attributeType><drawType>0</drawType><comcode>0</comcode><changeTyp>3</changeTyp>
<master>false</master><slave>false</slave></columns></rows>''' for index in indexes)
            payload = f'''<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>
<startCommand xmlns="{SERVICE}"><sessionid xmlns="">{escape(session_id)}</sessionid>
<commandid xmlns="">5021</commandid><changedAttributes xmlns="">
<complexAttributes behavior="0" identifier="dokinhaltselemente">{selection}</complexAttributes>
</changedAttributes><param xmlns=""><version>0</version></param></startCommand></soap:Body></soap:Envelope>'''
            body = parse_soap_body(self.soap_request('SessionObject', payload.encode('utf-8')))
            result = body.find(f'{{{SERVICE}}}startCommandResponse/return')
            if result is None or result.get('serviceName') != 'MESSAGE_LIST':
                raise ValueError('Der Server hat keine Löschbestätigung geliefert.')
            params = {entry.findtext('key'): entry.find('value') for entry in result.findall('serviceParams/entries')}
            command = params.get('commandId')
            message = params.get('message')
            content = params.get('listContent')
            names = [row.findall('entries')[1].text or '' for row in content.findall('entries')
                     if len(row.findall('entries')) >= 2] if content is not None else []
            if (command is None or command.text != '5021' or message is None or not message.text
                    or sorted(names) != sorted(file.name for file in files)):
                raise ValueError('Die Löschbestätigung passt nicht zu den ausgewählten Dateien.')
            return {'session_id': session_id, 'object_id': object_id, 'message': message.text, 'names': names}

    def confirm_file_deletion(self, session_id, confirmed=True):
        payload = f'''<soap:Envelope xmlns:soap="{SOAP}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
xmlns:xsd="http://www.w3.org/2001/XMLSchema"><soap:Body><endCommand xmlns="{SERVICE}">
<sessionid xmlns="">{escape(session_id)}</sessionid><commandid xmlns="">5021</commandid>
<serviceParams xmlns=""><entries><key xsi:type="xsd:string">messagereturn</key>
<value xsi:type="xsd:byte">{1 if confirmed else 2}</value></entries><version>0</version></serviceParams>
</endCommand></soap:Body></soap:Envelope>'''
        def send_command(payload, command):
            body = parse_soap_body(self.soap_request('SessionObject', payload.encode('utf-8')))
            response = body.find(f'{{{SERVICE}}}{command}Response')
            if response is None:
                raise ValueError('Der Server hat den Löschbefehl nicht bestätigt.')
            result = response.find('return')
            if result is not None and result.get('serviceName'):
                raise ValueError('Der Server meldet eine weitere Rückfrage statt eines abgeschlossenen Löschvorgangs.')

        with self._lock:
            send_command(payload, 'endCommand')
            if not confirmed:
                return
            payload = f'''<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>
<startCommand xmlns="{SERVICE}"><sessionid xmlns="">{escape(session_id)}</sessionid>
<commandid xmlns="">5021</commandid><changedAttributes xmlns=""/>
<param xmlns=""><version>0</version></param></startCommand></soap:Body></soap:Envelope>'''
            send_command(payload, 'startCommand')
            payload = f'''<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>
<endCommand xmlns="{SERVICE}"><sessionid xmlns="">{escape(session_id)}</sessionid>
<commandid xmlns="">5021</commandid><serviceParams xmlns=""><version>0</version></serviceParams>
</endCommand></soap:Body></soap:Envelope>'''
            send_command(payload, 'endCommand')

    def upload_file(self, object_id, path):
        """Stream a local file to the selected object's WebDAV collection."""
        object_id = int(object_id)
        if object_id <= 0:
            raise ValueError('Für den Upload ist eine gültige Objekt-ID erforderlich.')
        path = Path(path)
        url = f'{self.server_url}/webdav/{object_id}/{quote(path.name, safe="")}'
        with self._lock:
            if self._closed:
                raise RuntimeError('Die VIS-Verbindung ist geschlossen.')
            with path.open('rb') as source:
                with self.session.put(url, data=source,
                                      headers={'Content-Type': 'application/octet-stream'},
                                      timeout=(10, 60), allow_redirects=False) as response:
                    if response.status_code == 401:
                        raise ValueError('Kerberos-Anmeldung fehlgeschlagen. Ticket mit klist/kinit prüfen.')
                    if 300 <= response.status_code < 400:
                        raise ValueError('Der Upload wird umgeleitet. Bitte den Serverpfad prüfen.')
                    response.raise_for_status()

    def download_file(self, file, destination=None):
        """Download a complete file to a private temporary directory."""
        if not file.path:
            raise ValueError('Für diese Datei ist kein Download-Pfad vorhanden.')
        url = urljoin(self.server_url + '/', file.path)
        target, base = urlsplit(url), urlsplit(self.server_url)
        def origin(parts):
            return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)
        if (origin(target) != origin(base) or target.username is not None
                or target.password is not None or target.fragment):
            raise ValueError('Der Download-Pfad gehört nicht zum angemeldeten Server.')
        filename = Path(file.name.replace('\\', '/')).name
        if filename in ('', '.', '..') or '\0' in filename:
            filename = f'Datei-{file.file_id}'
        save_path = Path(destination) if destination is not None else None
        directory = Path(tempfile.mkdtemp(prefix='ultrasmartclient-',
                                         **({'dir': save_path.parent} if save_path is not None else {})))
        destination = save_path if save_path is not None else directory / filename
        partial = directory / '.download.part'
        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError('Die VIS-Verbindung ist geschlossen.')
                if self.debug:
                    print(f'>>> FILE GET {url}', flush=True)
                with self.session.get(url, stream=True, timeout=(10, 30), allow_redirects=False) as response:
                    if self.debug:
                        print(f'<<< FILE RESPONSE {url} HTTP {response.status_code}', flush=True)
                    if response.status_code == 401:
                        raise ValueError('Kerberos-Anmeldung fehlgeschlagen. Ticket mit klist/kinit prüfen.')
                    if 300 <= response.status_code < 400:
                        raise ValueError('Der Download wird umgeleitet. Bitte den Dateipfad prüfen.')
                    response.raise_for_status()
                    with partial.open('wb') as output:
                        for chunk in response.iter_content(chunk_size=65536):
                            if chunk:
                                output.write(chunk)
            partial.replace(destination)
            if save_path is not None:
                directory.rmdir()
            return destination
        except Exception:
            partial.unlink(missing_ok=True)
            directory.rmdir()
            raise

    def fetch_children(self, repository_id, parent_id=-1):
        """Read every page of the original client's OData tree endpoint."""
        parent_id = int(parent_id)
        if repository_id is None and parent_id == -1:
            raise ValueError('Für Ablagewurzeln ist eine Ablagen-ID erforderlich.')
        repository_filter = f'UablageId eq {int(repository_id)}L and ' if repository_id is not None else ''
        endpoint = self.server_url + '/vistree/BOs()'
        fields = ('AbgeschlossenAm,Datum,ObjektartId,ObjId,OrdnertypId,Name,Gz,'
                  'VaterobjartId,VaterobjId,ChildCount,Abgeschlossen,Gesperrt,Dringlich,'
                  'VaterNr,Rights,Isroot,UablageId,RelCount,MappeObjektartId,MappeObjId,'
                  'MappeStatusId,MappeTypId,Prim,TypId,VorgangtypId,DokumenttypId,'
                  'GeaendertAm,GeaendertVon,Betreff,Kurzbez,GeloeschtAm,ObjekticonId,'
                  'ObjekttypId,PoolId')
        params = {
            '$filter': repository_filter + f'VaterobjId eq {parent_id}L and GeloeschtAm eq null',
            '$skip': 0, '$top': 50, '$select': fields,
            '$inlinecount': 'allpages', '$orderby': 'ObjArtOrder,VaterNr,ObjId',
        }
        children, seen = [], set()
        while True:
            url = endpoint + '?' + urlencode(params, quote_via=quote, safe='$,')
            payload = self.tree_get(url)
            rows, count, more = parse_tree_page(payload)
            for row in rows:
                try:
                    identifier = str(int(row['ObjId']))
                    child_count = int(row['ChildCount'])
                    typ = int(row.get('ObjekttypId') or 0)
                    if child_count < 0:
                        raise ValueError('Negative ChildCount')
                    name = next((row.get(field) for field in ('Name', 'Gz', 'Betreff', 'Kurzbez')
                                 if isinstance(row.get(field), str) and row[field].strip()), identifier)
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError('Ungültiger Objekteintrag in der Baumantwort.') from error
                if identifier in seen:
                    raise ValueError('Baum-Endpunkt liefert wiederholte Objekt-IDs; Seitennavigation prüfen.')
                seen.add(identifier)
                children.append(TreeItem(identifier, name, child_count > 0, typ, identifier, '',
                                         *(str(row.get(field)) if row.get(field) is not None else ''
                                           for field in ('Gz', 'VaterNr', 'Kurzbez', 'Betreff',
                                                         'GeaendertAm', 'GeaendertVon')),
                                         object_kind=int(row['ObjektartId']) if row.get('ObjektartId') is not None else None,
                                         icon_id=int(row.get('ObjekticonId') or 0),
                                         completed=str(row.get('Abgeschlossen') or '').strip() == '1'))
            params['$skip'] += len(rows)
            if not rows:
                if more or count is not None and params['$skip'] < count:
                    raise ValueError('Unvollständige Seitennavigation in der Baumantwort.')
                return children
            if count is not None:
                if params['$skip'] >= count and not more:
                    return children
            elif len(rows) < params['$top'] and not more:
                return children


ATOM = 'http://www.w3.org/2005/Atom'
ODATA_META = 'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata'
ODATA_DATA = 'http://schemas.microsoft.com/ado/2007/08/dataservices'


def parse_tree_page(payload):
    """Read OData Atom entries, including typed properties and inline count."""
    try:
        feed = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ValueError('Baum-Endpunkt liefert keine gültige XML-Antwort.') from error
    if feed.tag == f'{{{ODATA_META}}}error':
        raise ValueError('Baum-Endpunkt meldet einen Fehler: ' +
                         (feed.findtext(f'{{{ODATA_META}}}message') or 'Unbekannter Fehler'))
    if feed.tag != f'{{{ATOM}}}feed':
        raise ValueError('Baumantwort enthält keinen Atom-Feed.')
    rows = []
    for entry in feed.findall(f'{{{ATOM}}}entry'):
        properties = entry.find(f'{{{ATOM}}}content/{{{ODATA_META}}}properties')
        if properties is None:
            properties = entry.find(f'{{{ODATA_META}}}properties')
        if properties is None:
            raise ValueError('Atom-Eintrag enthält keine Objekteigenschaften.')
        rows.append({field.tag[len(ODATA_DATA) + 2:]:
                     None if field.get(f'{{{ODATA_META}}}null') in ('true', '1') else field.text or ''
                     for field in properties if field.tag.startswith('{' + ODATA_DATA + '}')})
    count = feed.findtext(f'{{{ODATA_META}}}count')
    if count is not None:
        try:
            count = int(count)
            if count < 0:
                raise ValueError()
        except (TypeError, ValueError) as error:
            raise ValueError('Ungültige Gesamtanzahl in der Baumantwort.') from error
    more = any(link.get('rel') == 'next' for link in feed.findall(f'{{{ATOM}}}link'))
    return rows, count, more
