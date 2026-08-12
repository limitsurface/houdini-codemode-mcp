# Houdini Recipes

Use this guidance when discovering, applying, creating, or managing Houdini
recipes.

## Recipe Categories

Houdini has four recipe categories:

- **Tool recipes** create one or more nodes and appear alongside node types in
  Tab menus.
- **Decoration recipes** apply to an existing central node, create surrounding
  items, and may rewire connections.
- **Node presets** change parameters and optionally contents on an existing
  node.
- **Parameter presets** apply values to a parameter or multiparm.

Do not treat decorations or presets as ordinary creatable nodes. Tool and
decoration recipes may create multiple nodes or other network items, so inspect
the returned item map.

## Code Mode Workflow

There is no `ctx.recipe` helper. Use one complete `houdini_code_run` program
with raw `hou` only when the required HOM recipe API has been verified in the
prepared help. Keep discovery, application or creation, and post-change
inspection in that one run; emit only a bounded summary. Do not request
drop-on-wire or click placement through code: those modes wait for Network
Editor input.

Treat a forceful replacement of an existing recipe key as an in-place
overwrite. Do not delete individual recipe definitions through code. Direct
Data HDA definition destruction can race Houdini's background recipe and help
indexing. Use Houdini's Recipe Manager, or uninstall an entire explicitly owned
recipe library outside Code Mode.

## Local Houdini References

- Recipe overview and categories:
  `help_prepared/network/recipes.txt`
- Recipe scripting, application contexts, and pre/post scripts:
  `help_prepared/network/recipe_scripting.txt`
- Recipe Builder:
  `help_prepared/network/recipe_builder.txt`
- Declarative recipe data format:
  `help_prepared/network/recipe_format.txt`
- HOM recipe save, apply, and inspection functions:
  `help_prepared/hom/hou/data.txt`
