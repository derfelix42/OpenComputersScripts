local component = require("component")
local term = require("term")
local event = require("event")
local gpu = component.gpu

local rs = component.block_refinedstorage_interface
local refresh = 3 -- seconds

local function fmt(n)
  local s = tostring(n)
  while true do
    s, k = s:gsub("^(-?%d+)(%d%d%d)", "%1,%2")
    if k == 0 then break end
  end
  return s
end

while true do
  local items = rs.getItems()

  table.sort(items, function(a, b)
    return a.size > b.size
  end)

  local w, h = gpu.getResolution()
  term.clear()

  gpu.set(1, 1, ("Top RS items - refresh %ss"):format(refresh):sub(1, w))

  for y = 2, math.min(#items + 1, h) do
    local stack = items[y - 1]
    local name = stack.label or stack.name or "unknown"
    local text = string.format("%2d. %s: %s", y - 1, name, fmt(stack.size))
    gpu.set(1, y, text:sub(1, w))
  end

  event.pull(refresh)
end