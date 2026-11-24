# VAPI Documentation

## Transport and identifiers

`BASE` is the configured tenant URL, for example `https://vis.example.org/vis/TENANT-ID`. All requests should use a shared HTTP requests session with Kerberos challenge-based authentication and shared cookies.

| Identifier | Meaning |
| --- | --- |
| `obj_id`, `ObjId`, `BoId` | Business object ID; not a session ID |
| `obj_typ`, `ObjektartId` | Object kind, e.g. 1 Akte, 330 top-level Ablage (use returned `ObjektartId`), 3 Vorgang, 12 Eingang, 14 internes Schreiben, 15 Ausgang |
| `typId`, `ObjekttypId`, `dokumenttyp_id` | Configured subtype; distinct from object kind |
| `pool_id`, `PoolId` | Pool ID; not interchangeable with the Ablage object ID |
| `instanceId` / `sessionid` | Server-issued object or service session, illustrated as `O123` or `S456` |
| `rows/@index` | Session-local row index, not a persistent object/file/reference ID |
| `idvalue` | ID behind a displayed combo value; use the ID rather than its translated label |

The client resolves persistent IDs against current session rows before selecting them. Do not reuse row indexes from another session. Tenant IDs, parent IDs, pool IDs, and session IDs must come from configuration or responses, not recorded examples.

## SOAP conventions

SOAP requests are POSTs to `BASE/service/{service}` with `Content-Type: application/soap+xml; charset=utf-8`. Use SOAP 1.2 and the service namespace `http://services.visj.pdv.de`. Operation children are generally **unqualified** (LOL), using `xmlns=""` under a default-namespaced operation.

Complete request example:

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <s:Body>
    <createGetBoSession xmlns="http://services.visj.pdv.de">
      <obj_id xmlns="">123</obj_id>
      <obj_typ xmlns="">3</obj_typ>
    </createGetBoSession>
  </s:Body>
</s:Envelope>
```

Subsequent SOAP examples show the operation inside this envelope. An operation `foo` normally returns `fooResponse` in the service namespace, containing unqualified `return` elements. `serviceParams/entries` carry typed key/value pairs. The general command helpers send version `0`, including when copying returned parameters. The tasks overview separately tracks its returned version.

### SOAP operation inventory

| Service | Operation | Inputs | Response used |
| --- | --- | --- | --- |
| `UserRepository` | `getUserInfo` | `id=-1` | `return/id`, `return/displayName` |
| `UserRepository` | `getStellvertreterFuerList` | None | Repeated `return`: `id`, name fields, `stelle`, `active` |
| `UserRepository` | `setStellvertreterFuer` | `adm_id`: selected user ID, or `-10000` to end delegation | `setStellvertreterFuerResponse`; then refresh user info, picture, and delegation list |
| `UserRepository` | `getUserPicture` | Current user `id` | Base64 `return` |
| `UserRepository` | `setUserPicture` | Base64 `data`; empty to remove | Presence of `setUserPictureResponse` |
| `MandantenRepository` | `getObjektartInhaltChildList` | Parent `objektartId`, parent subtype `typId` | `return/itemList/text` and `id` |
| `SessionObject` | `createGetBoSession` | `obj_id`, `obj_typ` | Object context and `instanceId` |
| `SessionObject` | `createNewBoSession` | New `obj_typ`, `parent_id`, `pool_id`, `param/version=0` | Temporary object context, subtype choices, object ID |
| `SessionObject` | `createServiceSession` | `serviceName`, typed `serviceParams` | Service context and `instanceId` |
| `SessionObject` | `startCommand` | `sessionid`, `commandid`, `changedAttributes`, `param` | Context changes, dialog/service name, parameters/messages |
| `SessionObject` | `endCommand` | `sessionid`, `commandid`, `serviceParams` | Completion/context changes/parameters |
| `SessionObject` | `getComplexAttributes` | `sessionid`, `identifiers=iter@trefferliste` | Template collection |
| `SessionObject` | `getComplexAttribute` | `sessionid`, `identifier` | One collection: `iter@trefferliste`, `links`, or `bezuege` |
| `SessionObject` | `getComboList` | `sessionid`, `attrId=erledigung` | Combo list; an empty HTTP body is also accepted |
| `SessionObject` | `getComboLists` | `sessionid`, repeated `attrIds` | Repeated combo lists |
| `SessionObject` | `getTreeData` | **`sessionId`**, `treeName=tree` | `return/instanceId`, `id`, `rootName` |
| `SessionObject` | `getFlatTreeItemList` | **`sessionId`**, node `id`, `force=false` | Repeated nodes with text, ID, `dataBaseId`, `hasChildren` |
| `SessionObject` | `cancel` | `sessionid` | Service session cancellation |

`cancel` is different from the parent object's command `1003`.

### User data examples

```xml
<getUserInfo xmlns="http://services.visj.pdv.de"><id xmlns="">-1</id></getUserInfo>
```

```xml
<v:getUserInfoResponse xmlns:v="http://services.visj.pdv.de">
  <return><id>171</id><displayName>Example, User</displayName></return>
</v:getUserInfoResponse>
```

```xml
<getStellvertreterFuerList xmlns="http://services.visj.pdv.de"/>
```

```xml
<v:getStellvertreterFuerListResponse xmlns:v="http://services.visj.pdv.de">
  <return><id>172</id><displayName>Other User</displayName><stelle>Office</stelle><active>true</active></return>
</v:getStellvertreterFuerListResponse>
```

The name fallback order is `displayName`, `anredeName`, `userName`, `name`, then ID.

```xml
<getUserPicture xmlns="http://services.visj.pdv.de"><id xmlns="">171</id></getUserPicture>
```

```xml
<v:getUserPictureResponse xmlns:v="http://services.visj.pdv.de"><return>BASE64_IMAGE_BYTES</return></v:getUserPictureResponse>
```

```xml
<setUserPicture xmlns="http://services.visj.pdv.de"><data xmlns="">BASE64_IMAGE_BYTES</data></setUserPicture>
```

```xml
<v:setUserPictureResponse xmlns:v="http://services.visj.pdv.de"/>
```

## Object details and history

`fetch_object_details` makes one `createGetBoSession` call. It extracts links, references, properties, tasks, reminders, and history from that response. Opening Historie uses the cached history, with no additional history request.

Abbreviated response to the complete SOAP request above:

```xml
<v:createGetBoSessionResponse xmlns:v="http://services.visj.pdv.de">
  <return instanceId="O123">
    <simpleAttributes identifier="betreff" name="Betreff" idvalue="0" behavior="1">
      <value>Example subject</value><drawType>1</drawType>
    </simpleAttributes>
    <complexAttributes identifier="links">
      <rows index="0">
        <columns identifier="name"><value>Website</value></columns>
        <columns identifier="url"><value>https://example.org</value></columns>
      </rows>
    </complexAttributes>
    <complexAttributes identifier="bezuege">
      <rows index="0">
        <columns identifier="bez_id"><value>900</value></columns>
        <columns identifier="ziel_obj_id"><value>456</value></columns>
        <columns identifier="objektart_id"><value>14</value></columns>
        <columns identifier="objekticon_id"><value>14</value></columns>
        <columns identifier="name"><value>Related document</value></columns>
      </rows>
    </complexAttributes>
    <complexAttributes identifier="ggvermerke">
      <rows index="2">
        <columns identifier="ggv_id"><value>789</value></columns>
        <columns identifier="kategorie" idvalue="-502"><value>bitte Rücksprache</value></columns>
        <columns identifier="kategorie_typ" idvalue="-203"><value>Bearbeitungsaufgaben</value></columns>
        <columns identifier="erlassen_fuer_id" idvalue="171"><value>Example, User</value></columns>
      </rows>
    </complexAttributes>
    <complexAttributes identifier="wiedervorlagen"/>
    <complexAttributes identifier="historienelemente">
      <rows index="0">
        <columns identifier="datum"><value>24.11.2026 10:30</value></columns>
        <columns identifier="name"><value>Betreff</value></columns>
        <columns identifier="neu"><value>Example subject</value></columns>
        <columns identifier="alt"><value>Old subject</value></columns>
        <columns identifier="durch"><value>Example, User</value></columns>
      </rows>
    </complexAttributes>
  </return>
</v:createGetBoSessionResponse>
```

Other collections used are `dokinhaltselemente` for file selection and `trefferelemente` in the tasks service. Properties include `behavior`, `drawType`, and inline or context-level `comboList` data. The GUI enables editable fields when `behavior="1"`.

## Commands

All IDs below are sent by the current implementation. Except where a sequence explicitly differs, a command consists of `startCommand` followed by `endCommand` on the same session (cool thing to have 2 requests for everything what you want to do!).

| ID | Client use | Context / special parameters |
| --- | --- | --- |
| `1001` | Apply a service editor or confirm user selection | `GGVEDIT`, `BEARBEITEN`, or `NUTZERAUSWAHL`; end includes `SERVICE_END_COMMAND=1001`. User selection returns `userList` for the parent command. |
| `1002` | Apply object changes | Property saves, creation, quick-task completion, and Stellvertreter addition/deletion after `205000`/`205001` end |
| `1003` | Cancel object editing or workflow-template selection | Object save prompt is answered with `messagereturn=2` to discard. Template cancellation sends end only with `SERVICE_END_COMMAND=1003`, then ends parent `3028`. |
| `1007` | Finish/save object | Runs after `1002` for property saves and object creation |
| `1037` | Begin property editing | Optional `bo.update.ignore.collection` copied from object context |
| `3004` | Delete workflow task | Select `ggvermerke` row by server index; end has empty service parameters, version `0`. Requires edit mode; Save remains separate. |
| `3005` | Complete task | Select `ggvermerke` row, set `erledigung` |
| `3007` | Delete references | Select `bezuege`; end sends `messagereturn=1` |
| `3008` | Create reminder | Start includes empty simple attribute `auslauf` |
| `3010` | Create workflow task | Pending parent-object edit |
| `3014` | Delete link | Select `links`; pending parent-object edit |
| `3021` | Delete reminder (Wiedervorlage) | Select `wiedervorlagen` row by server index; end has empty service parameters, version `0`. Requires edit mode; Save remains separate. |
| `3028` | Open/finish workflow-template selection | Start returns `GGVMUSTERVERWALTUNG`; end runs in the parent object session after service `200404` or `1003`, passing returned service parameters. |
| `5020` | Rename file | Select `dokinhaltselemente`; returns service `BEARBEITEN` |
| `5021` | Delete files | Confirmation service `MESSAGE_LIST`, then follow-up deletion pair |
| `6146` | Unlock object | Start includes empty `auslauf` |
| `6154` | Open workflow task editor | Select `ggvermerke`; returns `GGVEDIT` |
| `30051` | Redirect task | Recipient/category/task/due-date parameters |
| `30052` | Reject task | Select row and rejection note |
| `200404` | Apply selected workflow template | Select `iter@trefferliste`; end includes `SERVICE_END_COMMAND=200404` |
| `202705` | Select user in Stellvertreter picker | `NUTZERAUSWAHL` session; start sets simple attribute `tree` to the node’s `selectedValue` (e.g. `0/3/(172)`), then plain end with version `0`. |
| `205000` | Add Stellvertreter | Start in `STELLVERTRETUNGADMINISTRATION` opens `NUTZERAUSWAHL`. After `202705` and `1001`, end in the administration session passes the returned `userList`, followed by `1002` start/end in that same session. |
| `205001` | Delete Stellvertreter | In `STELLVERTRETUNGADMINISTRATION`, select the server row index in `tableStellvertreter`; start has empty `param` version `0`, end has empty `serviceParams` version `0`. Then send `1002` start/end in the same session before refreshing both Stellvertreter lists. |
| `1470100018` | Load my tasks | Tasks service session; start only, tracked version |

Stellvertreter deletion uses command `205001` in the management session. It selects the row in `tableStellvertreter`, sends `205001` start/end followed by `1002` start/end, and refreshes both the management list and `getStellvertreterFuerList`.

### Command and response examples

A simple attribute update (the same structure is used for `betreff`, `auslauf`, and other simple property changes):

```xml
<startCommand xmlns="http://services.visj.pdv.de">
  <sessionid xmlns="">O123</sessionid><commandid xmlns="">1002</commandid>
  <changedAttributes xmlns="">
    <simpleAttributes identifier="betreff" idvalue="0" maxLength="0" behavior="0">
      <value>New subject</value><attributeType>0</attributeType><drawType>0</drawType>
      <comcode>0</comcode><changeTyp>3</changeTyp><master>false</master><slave>false</slave>
    </simpleAttributes>
  </changedAttributes>
  <param xmlns=""><version>0</version></param>
</startCommand>
```

```xml
<v:startCommandResponse xmlns:v="http://services.visj.pdv.de">
  <return serviceName="">
    <changedSessionContext instanceId="O123">
      <simpleAttributes identifier="obj_id"><value>456</value></simpleAttributes>
      <simpleAttributes identifier="betreff"><value>New subject</value></simpleAttributes>
    </changedSessionContext>
    <serviceParams><version>1</version></serviceParams>
  </return>
</v:startCommandResponse>
```

```xml
<endCommand xmlns="http://services.visj.pdv.de">
  <sessionid xmlns="">O123</sessionid><commandid xmlns="">1002</commandid>
  <serviceParams xmlns=""><version>0</version></serviceParams>
</endCommand>
```

```xml
<v:endCommandResponse xmlns:v="http://services.visj.pdv.de"><return/></v:endCommandResponse>
```

Empty `return` is sufficient for many command acknowledgements. A nonempty `serviceName` instead requests another service/dialog and must be handled by the specific flow.

Row-selection example for deleting a reference:

```xml
<startCommand xmlns="http://services.visj.pdv.de">
  <sessionid xmlns="">O123</sessionid><commandid xmlns="">3007</commandid>
  <changedAttributes xmlns="">
    <complexAttributes behavior="0" identifier="bezuege">
      <rows focused="false" selected="true" style="0" styleColor="0" visible="false"
            index="0" dragDropDataObjId="0" dragDropTyp="0" uniqueId="0">
        <columns identifier="__select" idvalue="0" maxLength="0" behavior="0">
          <value>1</value><attributeType>0</attributeType><drawType>0</drawType>
          <comcode>0</comcode><changeTyp>3</changeTyp><master>false</master><slave>false</slave>
        </columns>
      </rows>
    </complexAttributes>
  </changedAttributes>
  <param xmlns=""><version>0</version></param>
</startCommand>
```

```xml
<v:startCommandResponse xmlns:v="http://services.visj.pdv.de">
  <return serviceName="MESSAGE">
    <serviceParams>
      <entries><key>commandId</key><value>3007</value></entries>
      <entries><key>messageType</key><value>2</value></entries>
      <entries><key>message</key><value>Möchten Sie den Bezug wirklich löschen?</value></entries>
    </serviceParams>
  </return>
</v:startCommandResponse>
```

```xml
<endCommand xmlns="http://services.visj.pdv.de">
  <sessionid xmlns="">O123</sessionid><commandid xmlns="">3007</commandid>
  <serviceParams xmlns="">
    <entries><key xsi:type="xsd:string">messagereturn</key><value xsi:type="xsd:byte">1</value></entries>
    <version>0</version>
  </serviceParams>
</endCommand>
```

The reference-deletion flow accepts confirmation types `2` and `6` for command `3007`. Its start response can contain the **old** collection; only the end response replaces the pending reference list. Link deletion uses command `3014`, collection `links`, and a plain end with version `0`. Both leave the parent object in edit mode: the user must Save (`1002`, `1007`) or Cancel (`1003`).

### Workflow task, reminder, and template sequences

- New task: obtain/reuse object session → `3010` start/end → show pending rows.
- New reminder: obtain/reuse object session → `3008` start/end with empty `auslauf` → show pending reminders.
- Edit existing open task: begin parent editing with `1037` start/end, resolve its `ggv_id` to the current session row, then use the editor sequence below. Completed tasks are rejected; returned field permissions remain authoritative.
- Edit task: `6154` start with row selection → `createServiceSession(GGVEDIT)` using returned parameters → combo requests → `1001` start/end in the editor. Parent-object Save remains separate.
- Workflow editor category changes use `idvalue` with `changeTyp=2` and **no value element**; other changed fields use `changeTyp=3`. Recipient values use `--;USER_ID;DISPLAY_NAME;`.
- Templates: `3028` start → `createServiceSession(GGVMUSTERVERWALTUNG)` → `getComplexAttributes` and `getComplexAttribute` for `iter@trefferliste` → `200404` start/end in the service session. Closing then sends `3028` end in the parent object session with the returned service parameters. Aborting sends `1003` end in the service session instead of `200404`, followed by `3028` end. Parent changes remain pending.
- Complete: `3005` start/end → `1002` start/end.
- Reject: `30052` start/end → `1002` start/end to save the rejection.
- Redirect: `30051` start/end → `1002` start/end.

Quick-task start parameters include `de.pdv.visj.business.rule.Commands.APPLY_AFTER_COMMAND_ID` equal to the command ID.

Rejection and redirection send only the selected `ggvermerke` row, using its current session index, `__select=1`, and the entered `erledigung` note. Other task rows are omitted.

Redirect additionally sends:

| Parameter | XML type | Value |
| --- | --- | --- |
| `erlassen_fuer_id` | int | Recipient ID |
| `erlassen_fuer` | string | Recipient name |
| `kategorie` | string | Category ID |
| `pkg_kategorie` | string | Source task package category ID; fallback `-11008` |
| `ggv_multi_receivers` | string | `--;171;Example, User;` |
| `aufgabe` | string | Task text |
| `termin` | string | `dd.MM.yyyy` |
| `Geschaeftsgang.QUELLE_ERLEDIGEN` | boolean | `true` |

Category options for quick redirect come from OData `GGKategories()`, not the potentially read-only `GGVEDIT` session.

### Object creation

1. `createGetBoSession` for the selected parent supplies its pool ID and subtype.
2. POST to `MandantenRepository`:

```xml
<getObjektartInhaltChildList xmlns="http://services.visj.pdv.de">
  <objektartId xmlns="">3</objektartId><typId xmlns="">-150</typId>
</getObjektartInhaltChildList>
```

```xml
<v:getObjektartInhaltChildListResponse xmlns:v="http://services.visj.pdv.de">
  <return><identifier>ObjekartInhaltChildList</identifier>
    <itemList><text>Eingang</text><id>12</id></itemList>
    <itemList><text>Internes Schreiben</text><id>14</id></itemList>
  </return>
</v:getObjektartInhaltChildListResponse>
```

3. Selecting a kind creates a temporary object session:

```xml
<createNewBoSession xmlns="http://services.visj.pdv.de">
  <obj_typ xmlns="">12</obj_typ><parent_id xmlns="">123</parent_id><pool_id xmlns="">8</pool_id>
  <param xmlns=""><version>0</version></param>
</createNewBoSession>
```

```xml
<v:createNewBoSessionResponse xmlns:v="http://services.visj.pdv.de">
  <return instanceId="O456">
    <simpleAttributes identifier="obj_id"><value>456</value></simpleAttributes>
    <simpleAttributes identifier="betreff"><value>Inherited subject</value></simpleAttributes>
    <simpleAttributes identifier="dokumenttyp_id" idvalue="-100"><value>Angebot</value></simpleAttributes>
    <comboList><identifier>dokumenttyp_id</identifier>
      <itemList><text>Angebot</text><id>-100</id></itemList>
      <itemList><text>Brief</text><id>-101</id></itemList>
    </comboList>
  </return>
</v:createNewBoSessionResponse>
```

4. Subtype list key is `aktentyp_id`, `ablagetyp_id`, `vorgangtyp_id`, or `dokumenttyp_id` according to kind. Switching kinds cancels the preceding temporary session.
5. Anlegen sends `1002` start with `betreff` and, if changed, the subtype identifier/value, then `1002` end, `1007` start with empty attributes, and `1007` end. This subtype handling uses the generic property-command representation, distinct from the workflow editor category representation above.
6. The new object ID comes from returned `obj_id` attributes, falling back to the temporary context's object ID. The GUI refreshes repositories and opens that object.

## Service sessions, combos, and user selection

Service sessions are created through `SessionObject`:

```xml
<createServiceSession xmlns="http://services.visj.pdv.de">
  <serviceName xmlns="">GGVEDIT</serviceName>
  <serviceParams xmlns="">
    <entries><key xsi:type="xsd:string">boInstanceId</key><value xsi:type="xsd:string">123</value></entries>
    <entries><key xsi:type="xsd:string">rowindex</key><value xsi:type="xsd:int">2</value></entries>
    <version>0</version>
  </serviceParams>
</createServiceSession>
```

The parameter list above is illustrative: copy the **entire actual returned list**, including mode, readonly, tenant, and command parameters, rather than constructing a reduced list.

```xml
<v:createServiceSessionResponse xmlns:v="http://services.visj.pdv.de">
  <return instanceId="S456"><simpleAttributes identifier="kategorie" idvalue="-502" behavior="1"><value>bitte Rücksprache</value></simpleAttributes></return>
</v:createServiceSessionResponse>
```

| Service name | Parameter source / purpose |
| --- | --- |
| `GGVEDIT` | Parameters returned by command `6154` |
| `GGVMUSTERVERWALTUNG` | Parameters returned by `3028` |
| `BEARBEITEN` | Parameters returned by `5020` |
| `NUTZERAUSWAHL` | `mode=299` (int), `options=1610612800` (int), `artFilter` xList of ints 1/2/3 with version 1, empty `artAuswahlBlacklist` entry, tenant string in braces |
| `STARTSEITEAUFGABEN_SIMPLE_SMART` | Fixed task overview parameters listed below |

Task overview parameters: `formName=STARTSEITEAUFGABEN_SIMPLE_SMART`, `boType="19"`, `ignoreErlasser=true`, `richclient.user_and_allstellv=true`, `saveableWithCancel="false"`, empty string `prop_no_message_onempty_search`, `boState="32"`, `PARAM_ADD_COMPLEX_ATTR` as service `xList` containing string `trefferelemente` and version 1, and `mandant` in braces. See `TASKS_SESSION_REQUEST` for XML types. Subsequent `1470100018` start requests use the tracked session/version and return rows in `changedSessionContext/complexAttributes[@identifier='trefferelemente']` plus `serviceParams/version`.

Combo requests and example response:

```xml
<getComboList xmlns="http://services.visj.pdv.de"><sessionid xmlns="">S456</sessionid><attrId xmlns="">erledigung</attrId></getComboList>
```

```xml
<getComboLists xmlns="http://services.visj.pdv.de">
  <sessionid xmlns="">S456</sessionid>
  <attrIds xmlns="">kategorie</attrIds><attrIds xmlns="">kategorie_typ</attrIds>
  <attrIds xmlns="">aufgabe</attrIds><attrIds xmlns="">erledigung</attrIds><attrIds xmlns="">pkg_kategorie</attrIds>
</getComboLists>
```

```xml
<v:getComboListsResponse xmlns:v="http://services.visj.pdv.de">
  <return><identifier>kategorie</identifier><itemList><text>Prüfung</text><id>644</id></itemList></return>
  <return><identifier>erledigung</identifier></return>
</v:getComboListsResponse>
```

Collection requests:

```xml
<getComplexAttributes xmlns="http://services.visj.pdv.de"><sessionid xmlns="">S456</sessionid><identifiers xmlns="">iter@trefferliste</identifiers></getComplexAttributes>
```

```xml
<getComplexAttribute xmlns="http://services.visj.pdv.de"><sessionid xmlns="">S456</sessionid><identifier xmlns="">iter@trefferliste</identifier></getComplexAttribute>
```

```xml
<v:getComplexAttributeResponse xmlns:v="http://services.visj.pdv.de">
  <return identifier="iter@trefferliste"><rows index="0">
    <columns identifier="MusterId"><value>338</value></columns>
    <columns identifier="Name"><value>Example template</value></columns>
    <columns identifier="Description"><value>Description</value></columns>
  </rows></return>
</v:getComplexAttributeResponse>
```

`getComplexAttributesResponse` uses the same collection shape. Existing editing sessions also query `links` or `bezuege` through `getComplexAttribute` to resolve current rows before deletion.

After creating `NUTZERAUSWAHL`:

```xml
<getTreeData xmlns="http://services.visj.pdv.de"><sessionId xmlns="">S456</sessionId><treeName xmlns="">tree</treeName></getTreeData>
```

```xml
<v:getTreeDataResponse xmlns:v="http://services.visj.pdv.de"><return><instanceId>T789</instanceId><id>0</id><rootName>Aufbauorganisation</rootName></return></v:getTreeDataResponse>
```

```xml
<getFlatTreeItemList xmlns="http://services.visj.pdv.de"><sessionId xmlns="">T789</sessionId><id xmlns="">0</id><force xmlns="">false</force></getFlatTreeItemList>
```

```xml
<v:getFlatTreeItemListResponse xmlns:v="http://services.visj.pdv.de">
  <return id="node171" dataBaseId="Users/(171)" hasChildren="false"><text>Example, User</text></return>
</v:getFlatTreeItemListResponse>
```

The client derives a leaf's numeric user ID from the final component of `dataBaseId`. Close the selection/editor using its service session, not its tree instance:

```xml
<cancel xmlns="http://services.visj.pdv.de"><sessionid xmlns="">S456</sessionid></cancel>
```

```xml
<v:cancelResponse xmlns:v="http://services.visj.pdv.de"/>
```

## OData / Atom reads

GET requests send `Accept: application/atom+xml,application/xml`. Query values below are shown decoded for readability; the client URL-encodes them and uses OData integer suffix `L`.

| Endpoint under `BASE/vistree/` | Query |
| --- | --- |
| `Ablages()` | `$filter=TypId eq 2L`, `$orderby=Name` |
| `BOs()` | `$filter=UablageId eq REPOSITORY_IDL and VaterobjId eq PARENT_IDL and GeloeschtAm eq null`; omit UablageId for children outside a known repository; root parent is `-1L` |
| `Favoritens()` root | `$filter=AdmId eq ADMIN_IDL and VaterId eq 0L and (ArtId eq -1L or ArtId eq 0L)`, `$orderby=Reihenfolge`; current default admin ID is 171 |
| `Favoritens()` folder | First `$top=1&$filter=Id eq FOLDER_IDL`; if the response is the folder itself, query children by `AdmId`, `VaterId`, ArtId filter and Reihenfolge |
| `Files()` | `$filter=BoId eq OBJECT_IDL`, explicit file fields below |
| `GGKategories()` | `$filter=KategorieTyp eq TYPE_IDL and ObjektartId eq KIND_IDL`, `$orderby=Reihenfolge` |

`BOs()` uses `$skip=0`, `$top=50`, `$inlinecount=allpages`, `$orderby=ObjArtOrder,VaterNr,ObjId`; subsequent pages advance `$skip` by returned row count. Selected fields:

```text
AbgeschlossenAm,Datum,ObjektartId,ObjId,OrdnertypId,Name,Gz,
VaterobjartId,VaterobjId,ChildCount,Abgeschlossen,Gesperrt,Dringlich,
VaterNr,Rights,Isroot,UablageId,RelCount,MappeObjektartId,MappeObjId,
MappeStatusId,MappeTypId,Prim,TypId,VorgangtypId,DokumenttypId,
GeaendertAm,GeaendertVon,Betreff,Kurzbez,GeloeschtAm,ObjekticonId,
ObjekttypId,PoolId
```

`Files()` selects:

```text
Name,FileId,BoId,Path,Filesize,Flags,Modified,ModifiedBy,Created,CreatedBy,
Objcomment,Renditiontypes,Rights
```

Ablages, favorites, files, and categories follow Atom `rel="next"` links. The helper rejects cross-origin/different-endpoint links and cycles. BOs uses its own skip/count pagination and rejects repeated object IDs and incomplete pages.

Example request:

```http
GET BASE/vistree/BOs()?$filter=UablageId%20eq%2042L%20and%20VaterobjId%20eq%20-1L%20and%20GeloeschtAm%20eq%20null&$skip=0&$top=50&$inlinecount=allpages&$orderby=ObjArtOrder,VaterNr,ObjId
Accept: application/atom+xml,application/xml
```

Abbreviated Atom response:

```xml
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <m:count>1</m:count>
  <entry><content type="application/xml"><m:properties>
    <d:ObjId>123</d:ObjId><d:Name>Example object</d:Name>
    <d:ObjektartId>3</d:ObjektartId><d:ObjekttypId>-150</d:ObjekttypId>
    <d:ObjekticonId>3</d:ObjekticonId><d:ChildCount>0</d:ChildCount>
    <d:Abgeschlossen>1</d:Abgeschlossen>
  </m:properties></content></entry>
</feed>
```

`Abgeschlossen=1` produces the right-side tree lock icon. `ObjekticonId` controls the object icon; `ChildCount` controls expansion. For repositories, `ObjId`, not `PoolId`, is the tree identity. Property requests use the returned `ObjektartId` (e.g. 330), not `TypId` (2).

Other feeds use the same envelope, with these example property sets:

| Feed | Example properties (abbreviated) |
| --- | --- |
| Ablages | `ObjId=42`, `PoolId=8`, `Name=Registry`, `ChildCount=2`, `PoolTyp=1`, `TypId=2` |
| Favoritens | `Id=10`, `ObjId=123` (or `-1` for folder), `Name=Favorite`, `ObjekttypId=-150`, `ObjektartId=3`, `ObjekticonId=3`, `Reihenfolge=1` |
| Files | `Name=example.pdf`, `FileId=77`, `BoId=123`, `Path=webdav/123/example.pdf`, `Filesize=1024`, `Flags=0`, `Rights=255`, timestamps and user names |
| GGKategories | `KategorieId=-502`, `KategorieTyp=-203`, `ObjektartId=14`, `Name=bitte Rücksprache`, `Reihenfolge=26` |

Category request example:

```http
GET BASE/vistree/GGKategories()?$filter=KategorieTyp%20eq%20-203L%20and%20ObjektartId%20eq%2014L&$orderby=Reihenfolge
```

The type is the selected task row's `columns[@identifier='kategorie_typ']/@idvalue` from the already-loaded object response. The client queries that one type, rather than copying the multiple-type OR filter from the original browser capture. Category IDs come from `KategorieId`, labels from `Name`, with server ordering retained.

## Search

```http
POST BASE/vis_search/searching/simple?client=TENANT-ID
Accept: application/json
Content-Type: application/json
```

```json
{
  "offset": 0, "num": 100, "query": "Example",
  "filter": [], "fieldQueries": [], "facets": [], "facetFilter": [],
  "sortby": null, "sortdir": "asc"
}
```

Abbreviated response:

```json
{
  "resultset": {
    "results": [{
      "name": "schriftgut", "num": 2, "errorcode": 200, "aborted": false,
      "groups": [{
        "name": "default",
        "documents": [
          {"fields": [
            {"name": "obj_id", "value": "123"},
            {"name": "objektart_id", "value": 3.0},
            {"name": "doctype", "value": 3.0},
            {"name": "objekt_name", "value": "Example folder"},
            {"name": "score", "value": 100.0}
          ]},
          {"fields": [
            {"name": "obj_id", "value": "456"},
            {"name": "objektart_id", "value": 14.0},
            {"name": "doctype", "value": 14.0},
            {"name": "vfs_id", "value": "77"},
            {"name": "name", "value": "example.pdf"},
            {"name": "score", "value": 50.0}
          ]}
        ]
      }]
    }]
  }
}
```

The GUI debounces typing for 300 ms, ignores stale responses, groups results, and shows returned count versus total. Current search requests only the first 100 results; it does not paginate. `client` is derived from the configured tenant URL, without braces. File hits currently open their containing business object. Focus can reopen cached results without a new request.

## File operations

### Download and upload

Downloads use the `Files()` row's `Path`, resolved against `BASE/`, and a streaming GET. Only the configured origin is accepted. Files are written to a partial file and completed locally after a successful transfer.

```http
GET BASE/webdav/123/example.pdf
```

```http
HTTP/1.1 200 OK
Content-Type: application/pdf

(binary file bytes)
```

Uploads stream the local file using its URL-escaped basename:

```http
PUT BASE/webdav/123/example.pdf
Content-Type: application/octet-stream

(binary file bytes)
```

```http
HTTP/1.1 201 Created
```

The status above is illustrative; the client accepts successful non-redirect HTTP responses, not only 201.

### Rename

1. `createGetBoSession`; resolve file ID in `dokinhaltselemente/rows/columns[@identifier='id']`.
2. `5020` start, with selected row and other rows deselected.
3. Require `serviceName=BEARBEITEN`, `bearbeitenvalue` matching the existing filename, and `withExtension=false`.
4. `createServiceSession(BEARBEITEN)` with returned parameters.
5. `1001` start with simple attribute `eingabe` containing the new **basename without extension**.
6. `1001` end with `SERVICE_END_COMMAND=1001`. Require `bearbeitenreturn=TRUE` and the expected full `bearbeitenvalue`.
7. `cancel` the BEARBEITEN session (also on validation failure).
8. `5020` end on the object session with the returned parameters.

Example service parameters in the editor's successful end response:

```xml
<v:endCommandResponse xmlns:v="http://services.visj.pdv.de">
  <return><serviceParams>
    <entries><key>bearbeitenreturn</key><value>TRUE</value></entries>
    <entries><key>bearbeitenvalue</key><value>renamed.pdf</value></entries>
    <version>0</version>
  </serviceParams></return>
</v:endCommandResponse>
```

### Delete files

1. `createGetBoSession`; resolve selected file IDs to `dokinhaltselemente` row indexes.
2. `5021` start with selected rows; require `serviceName=MESSAGE_LIST`.
3. Validate `commandId=5021`, message, and filenames in `listContent` against the selected files, then show the confirmation.
4. `5021` end with `messagereturn` byte `1` (yes) or `2` (no).
5. If confirmed, send another `5021` start with empty attributes and `5021` end with version `0`.

Unlike deleting links/references, this flow has its own confirmation/follow-up sequence and is not deferred to the properties Save button.

## Errors and response handling

HTTP errors propagate; 401 generally becomes a Kerberos-specific error. SOAP Faults are parsed and surfaced. SOAP command message entries are routed to the application's message handler; error messages stop the operation. Unexpected service dialogs are rejected rather than treated as successful completion.

Examples of important distinctions:

- `MESSAGE` type 2/6 for reference deletion is an expected confirmation, answered by the recorded `messagereturn=1` sequence.
- `1003` cancellation only accepts the expected save-confirmation prompt (type 6); `messagereturn=2` discards changes.
- A read-only GGVEDIT context can return only the current category. It is not a complete forwarding category catalog.
- A successful start response does not substitute for its required end request.
- Before confirmation, a returned collection may still contain the soon-to-be-deleted row.

## Switching delegation

The user-picture menu sends the selected delegation user ID to `UserRepository`.
“Keine Stellvertretung” sends the fixed sentinel `-10000`.

```xml
<setStellvertreterFuer xmlns="http://services.visj.pdv.de">
  <adm_id xmlns="">170</adm_id>
</setStellvertreterFuer>
```

```xml
<v:setStellvertreterFuerResponse xmlns:v="http://services.visj.pdv.de"/>
```

After acknowledgement, the client calls `getUserInfo` with the selected user ID
(or `id=-1` when ending delegation),
`getUserPicture` using the refreshed user ID, and `getStellvertreterFuerList`.
It resets its task service session and updates the identity in windows sharing
the connection. Switching is blocked while those windows have pending property edits.

The delegation menu defaults to `Keine Stellvertretung` (`-10000`). Its checked
item tracks the last acknowledged switch, not the list entry's `active` flag.

Task and Wiedervorlagen deletion is available from the row context menu in edit mode. Tasks use `3004`, Wiedervorlagen use `3021`: `startCommand` selects the server row index in `ggvermerke` or `wiedervorlagen`, then `endCommand` sends empty service parameters with version 0. Deletions remain pending until the object is saved.

Stellvertreterverwaltung is available in the Start ribbon. It creates `STELLVERTRETUNGADMINISTRATION` with `PARAM_ADD_COMPLEX_ATTR=tableStellvertreter` and the current tenant, then loads `tableStellvertreter`. Adding starts `205000`, opens the returned `NUTZERAUSWAHL` service, selects the tree `selectedValue` with `202705` start/end, completes `1001` start/end, and returns the server-provided `userList` through `205000` end, followed by `1002` start/end in the administration session before refreshing the lists. Deletion uses `205001` start/end with the selected server row index in `tableStellvertreter`, followed by `1002` start/end in the same administration session. Successful changes refresh `getStellvertreterFuerList` and the management list.
