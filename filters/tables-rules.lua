--[[
tables-rules - adds vertical and horizontal rules to tables for LaTeX/PDF output.

Copyright (c) 2021 Christophe Agathon. MIT License.
Source: https://github.com/chrisaga/hk-pandoc-filters
--]]
local List = require 'pandoc.List'

local vars = {}

function get_vars(meta)
  vars.vrules = meta['tables-vrules']
  vars.hrules = meta['tables-hrules']
end

function repl_midrules(m1, m2)
  if m2:match('^\\[%w]+rule') then
    return m1 .. m2
  else
    return m1 .. '\\midrule\n' .. m2
  end
end

function fix_coldef(m1, m2)
  local n = m2:match('%(\\columnwidth %- ([%d%.]+)\\tabcolsep%)')
  if not n then
    n = m2:match('%(\\linewidth %- ([%d%.]+)\\tabcolsep%)')
  end

  return m1:gsub('[%d%.]+(\\tabcolsep)',
    string.format('%d', n + 2) .. '%1 - ' ..
    string.format('%d', 2 + n / 2) .. '\\arrayrulewidth') .. '|'
end

function fix_simplestyle(m1, m2, m3)
  return m1 .. m2:gsub('(.)', '%1|') .. m3
end

function fix_colsdefs(m)
  return m:gsub('^{@{}', '{|')
    :gsub('@{}}$', '}')
    :gsub('(>%b{}%l(%b{}))', fix_coldef)
    :gsub('({|)(%l+)(})', fix_simplestyle)
end

function adjust_p(m1, m2)
  return m1 .. m2:gsub('}$', ' -2\\tabcolsep -2\\arrayrulewidth}')
end

function fix_multicol(command, coldef, content)
  return command .. coldef:gsub('@%b{}', '|'):gsub('|?}$', '|}')
    :gsub('(p)(%b{})', adjust_p)
    .. content
end

function pad_minipage(m1, m2, m3)
  return m1 .. m2 .. '\\smallskip\n' .. m3
end

function Table(table)
  local returned_list
  local begin_env, env_content, end_env

  if not vars.vrules and not vars.hrules then
    return nil
  end

  if FORMAT:match 'latex' then
    begin_env, env_content, end_env =
      pandoc.write(pandoc.Pandoc({ table }), 'latex')
        :match('(\\begin{longtable}%b[]%b{})(.*)(\\end{longtable})')

    if vars.vrules then
      begin_env = begin_env:gsub('(%b{})$', fix_colsdefs)
      env_content = env_content:gsub(
        '(\\multicolumn%b{})(%b{})(%b{})',
        fix_multicol
      )
    end

    if vars.hrules then
      env_content = env_content:gsub('( \\\\\n)([\\%w]+)', repl_midrules)
        :gsub('(\\begin{minipage}%b[])(%b{})(.*\\end{minipage})', pad_minipage)
    end

    returned_list = List:new {
      pandoc.RawBlock('tex', begin_env .. env_content .. end_env),
    }
  end

  return returned_list
end

function Meta(meta)
  if not vars.vrules and not vars.hrules then
    return nil
  end

  local includes = [[
\usepackage{longtable,booktabs,array}
\usepackage{calc}
\usepackage{etoolbox}
\makeatletter
\patchcmd\longtable{\par}{\if@noskipsec\mbox{}\fi\par}{}{}
\makeatother
\IfFileExists{footnotehyper.sty}{\usepackage{footnotehyper}}{\usepackage{footnote}}
\makesavenoteenv{longtable}
\setlength{\aboverulesep}{0pt}
\setlength{\belowrulesep}{0pt}
\renewcommand{\arraystretch}{1.3}
]]

  if meta['header-includes'] then
    table.insert(meta['header-includes'], pandoc.RawBlock('tex', includes))
  else
    meta['header-includes'] = List:new { pandoc.RawBlock('tex', includes) }
  end

  return meta
end

return { { Meta = get_vars }, { Table = Table }, { Meta = Meta } }
