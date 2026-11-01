# rest-mapper

Careful polling of JSON APIs and mapping of their values, with no framework. It is the library behind the REST Mapper integration for Home Assistant.

- `paths` and `flatten`: address values in a response, and list what a response offers.
- `mapping`: read typed values and positions, and say why a read failed.
- `tracking`: follow list items by key.
- `client`: one GET with authentication, a size limit and typed outcomes.
- `policy`: decide when the next request may happen.

Package modules import each other relatively, so the package can be copied into another project.
