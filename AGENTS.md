Don't make a commit or API request without my permission.

# Follow proper API and page downloading etiquette:

Always follow these rules for both API requests and html pages!
As well as when using curl, wget, or python alike.

```markdown
## Behaviour

### Request limit

There is no hard speed limit on read requests, but be considerate and try not to take a site down. Most system administrators reserve the right to unceremoniously block you if you do endanger the stability of their site.

Making your requests in series rather than in parallel, by waiting for one request to finish before sending a new request, should result in a safe request rate. It is also recommended that you ask for multiple items in one request by:

*   Using the pipe character (`|`) whenever possible e.g. `titles=PageA|PageB|PageC`, instead of making a new request for each title.
*   Using a [generator](https://www.mediawiki.org/wiki/Special:MyLanguage/API:Query#Generators) instead of making a request for each result from another request.
*   Use GZip compression when making API calls by setting `Accept-Encoding: gzip` to reduce bandwidth usage.

Requests which make edits, modify state or otherwise are not read-only requests, *are* subject to [rate limiting](https://www.mediawiki.org/wiki/Special:MyLanguage/Manual:Rate_limits). The exact rate limit being applied might depend on the type of action, your user rights and the configuration of the website you are making the request to. The limits that apply to you can be determined by accessing the [action=query&amp;meta=userinfo&amp;uiprop=ratelimits](https://www.mediawiki.org/w/index.php?title=Special:ApiSandbox#action=query&amp;format=json&amp;meta=userinfo&amp;uiprop=ratelimits) API endpoint.

When you hit the request rate limit you will receive an [API error response](https://www.mediawiki.org/wiki/Special:MyLanguage/API:Errors_and_warnings) with the error code `ratelimited`. When you encounter this error, you may retry that request, however you should increase the time between subsequent requests. A common strategy for this is [Exponential backoff](https://en.wikipedia.org/wiki/Exponential_backoff).

### Parsing of revisions

While it is possible to query for results from a specific revision number using the `revid` parameter, this is an expensive operation for the servers. To retrieve a specific revision use the `oldid` parameter. For example:

> [api.php?action=parse&amp;format=json&amp;prop=images&amp;oldid=254862759](https://www.mediawiki.org/w/index.php?title=Special:ApiSandbox#action=parse&amp;format=json&amp;prop=images&amp;oldid=254862759)

### The maxlag parameter

If your task is not interactive, i.e. a user is not waiting for the result, you should use the `maxlag` parameter. The value of the `maxlag` parameter should be an integer number of seconds. For example:

> [api.php?action=query&amp;format=json&amp;titles=Main%20Page&amp;maxlag=1](https://www.mediawiki.org/w/index.php?title=Special:ApiSandbox#action=query&amp;format=json&amp;titles=Main%20Page&amp;maxlag=1)

This will prevent your task from running when the load on the servers is high. Higher values mean more aggressive behaviour, lower values are nicer.

See [Manual:Maxlag parameter](https://www.mediawiki.org/wiki/Special:MyLanguage/Manual:Maxlag_parameter) for more details.

### The User-Agent header

It is best practice to set a descriptive User-Agent header. To do so, use `User-Agent: clientname/version (contact information e.g. username, email) framework/version...`. For example in PHP:

```php
ini_set('user_agent', 'MyCoolTool/1.1 (https://example.org/MyCoolTool/; MyCoolTool@example.org) UsedBaseLibrary/1.4');
```

Do not simply copy the user-agent of a popular web browser. This ensures that if a problem does arise it is easy to track down where it originates.

If you are calling the API from browser-based JavaScript, you may not be able to influence the `User-Agent` header, depending on the browser. To work around this, use the `Api-User-Agent` header.

### Data formats

All new API users [should use JSON](https://www.mediawiki.org/wiki/Special:MyLanguage/API:Data_formats#Output). See [API:Data formats](https://www.mediawiki.org/wiki/Special:MyLanguage/API:Data_formats) for more details.

### Caching

If your requests obtain data that can be cached for a while, you should take steps to cache it, so you don't request the same data over and over again. Some clients may be able to cache data themselves, but for others (particularly JavaScript clients), this is not possible.

### POST requests

Whenever you're reading data from the web service API, you should try to use GET requests if possible, not POST, as the latter are not cacheable and, in [multi-datacenter](https://wikitech.wikimedia.org/wiki/Performance/Multi-DC_MediaWiki) configurations (including Wikimedia sites), may go to a farther data center.

In exceptional cases where you really need to use POST for a read request, such as calling `action=parse` with a long string of wikitext, consider setting the `Promise-Non-Write-API-Action: true` header. This helps ensure that your POST request is processed by an application server in the closest data center, if appropriate.

---

## Guidelines for Wikimedia wikis

In addition to the best practices described above, the following guidelines apply to using the Action API to access Wikimedia wikis. See also [the official guidelines about API usage](https://foundation.wikimedia.org/wiki/Special:MyLanguage/Policy:Wikimedia_Foundation_API_Usage_Guidelines) on Wikimedia Foundation Governance wiki.

### User-Agent policy

API requests to Wikimedia wikis must include a meaningful User-Agent header. See [User-Agent policy](https://foundation.wikimedia.org/wiki/Special:MyLanguage/Policy:User-Agent_policy) for more details.

### Rate limits

In addition to [rate limits](https://www.mediawiki.org/wiki/Special:MyLanguage/Manual:Rate_limits) based on user actions, API requests to Wikimedia wiki are subject to [API rate limits](https://www.mediawiki.org/wiki/Special:MyLanguage/Wikimedia_APIs/Rate_limits).

### Performance

Downloading data in bulk is not always extremely efficient using the Action API. On Wikimedia wikis, there are faster ways to get data in bulk, see [m:Research:Data](https://meta.wikimedia.org/wiki/Research:Data) and [wikitech:Portal:Data Services](https://wikitech.wikimedia.org/wiki/Portal:Data_Services) for more details.
```
