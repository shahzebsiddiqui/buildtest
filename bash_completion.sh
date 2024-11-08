# This is the bash completion script for buildtest
# For auto completion via compgen, options are sorted alphabetically in the format: <longoption> <shortoption> <subcommands>
# For more details see https://www.gnu.org/software/bash/manual/html_node/Programmable-Completion-Builtins.html

if test -n "${ZSH_VERSION:-}" ; then
  if [[ "$(emulate)" = zsh ]] ; then
    if ! typeset -f compdef >& /dev/null ; then
        # See https://zsh.sourceforge.io/Doc/Release/Completion-System.html##Use-of-compinit
        # ensure base completion support is enabled, ignore insecure directories
        autoload -U +X compinit && compinit -i
    fi
    if ! typeset -f complete >& /dev/null ; then
        # ensure bash compatible completion support is enabled. See  https://stackoverflow.com/questions/3249432/can-a-bash-tab-completion-script-be-used-in-zsh
        autoload -U +X bashcompinit && bashcompinit
    fi
    emulate sh -c "source '$0:A'"
    return # stop interpreting file
  fi
fi

_supported_colors()
{
  python -c "from rich.color import ANSI_COLOR_NAMES;print(' '.join(list(ANSI_COLOR_NAMES.keys())))"
}
# get a list of available color themes used for command completion for --theme option
_avail_color_themes ()
{
  python -c "from pygments.styles import STYLE_MAP; print(' '.join(list(STYLE_MAP.keys())))"
}

_buildtest_commands()
{
  buildtest commands --with-aliases
}
# get list of available tags
_avail_tags ()
{
  buildtest buildspec find --tags --terse --count=-1 --no-header 2>/dev/null
}

# get list of buildspecs in cache
_avail_buildspecs ()
{
  buildtest buildspec find --buildspec --terse --count=-1 --no-header 2>/dev/null
}


# list of available executors
_avail_executors ()
{
  buildtest config executors list
}

_all_executors()
{
  buildtest config executors list --all
}

# list of available compilers
_avail_compilers ()
{
  buildtest config compilers list
}

# list of test ids from report
_test_ids ()
{
  buildtest inspect list --terse --no-header | cut -d '|' -f 1
}
# list of available test names from buildspec cache
_buildspec_test_names()
{
  buildtest buildspec find --count=-1  --format name --terse --no-header | sort
}

# list of test names from report
_test_name ()
{
  buildtest inspect list --terse --no-header | cut -d '|' -f 2 | uniq | sort
}

_builder_names()
{
  buildtest inspect list --builder
}

# list of buildspecs from report
_test_buildspec ()
{
  buildtest inspect list --terse --no-header | cut -d '|' -f 3 | uniq | sort
}

# list of history id
_history_id ()
{
  buildtest history list --terse --no-header | cut -d '|' -f 1 | sort -g
}

_buildspec_cache_test_names()
{
  buildtest buildspec find --format name --terse --no-header --count=-1 | sort
}

_failed_tests()
{
  buildtest report --fail --format name --terse --no-header --count=-1 | uniq
}

# list of available maintainers for tab completion for 'buildtest buildspec maintainers find'
_avail_maintainers()
{
  buildtest buildspec maintainers --terse --no-header | sort
}

# list of filterfields
_avail_buildspec_filterfields()
{
  buildtest buildspec find --filterfields
}

# list of formatfields
_avail_buildspec_formatfields()
{
  buildtest buildspec find --formatfields
}

_avail_report_filterfields()
{
  buildtest report --filterfields
}

_avail_report_formatfields()
{
  buildtest report --formatfields
}

_avail_profiles()
{
  buildtest config profiles list
}

_buildtest_show_commands()
{
  python -c "from buildtest.cli import BuildTestParser; print(' '.join(BuildTestParser()._buildtest_show_commands))"
}

_buildtest_options()
{
  buildtest --listopts
}
#  entry point to buildtest bash completion function
_buildtest ()
{
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  declare -i offset="0"

  COMPREPLY=()   # Array variable storing the possible completions.

  main_opts=($(_buildtest_options))

  commands_with_input=( "--color" "--config" "-c" "--report" "-r" "--loglevel" "-l" "--editor" )   # Array variable storing commands which require an input argument from the user.

  for command in "${COMP_WORDS[@]}"
  do
    for element in "${main_opts[@]}"
    do

        if [[ "$command" == "$element" ]]; then
          
          if [[ "${commands_with_input[*]}" =~ $command ]];
          then
            ((offset+=2))
          else
            ((offset+=1))
          fi
        fi

    done

  done

  local next=${COMP_WORDS[1+offset]}
  
  case "$next" in
    build|bd)
      local shortoption="-b -e -et -f -m -n -s -t -u -x -xt"
      local longoption="--account --buildspec --display --dry-run --executor --executor-type --exclude --exclude-tags --filter --helpfilter --limit --maxpendtime --max-jobs --modules --module-purge --name --nodes --pollinterval --procs --profile --rebuild --rerun --remove-stagedir --retry --save-profile --strict --tags --testdir --timeout --unload-modules --validate --write-config-file"
      local allopts="${longoption} ${shortoption}"

      COMPREPLY=( "$( compgen -W "$allopts" -- "${cur}" )" )

      case "${prev}" in
        -e|--executor)
            COMPREPLY=( "$( compgen -W "$(_avail_executors)" -- "${cur}" )" )
            ;;
        -et|--executor-type)
            COMPREPLY=( "$( compgen -W "local batch" -- "${cur}" )" )
            ;;
        -t|--tag|-xt|--exclude-tags)
            COMPREPLY=( "$( compgen -W "$(_avail_tags)" -- "${cur}" )" )
            ;;
        -b|--buildspec|-x|--exclude)
            COMPREPLY=( "$( compgen -W "$(_avail_buildspecs)" -- "${cur}" )" )
            ;;
        -n|--name)
            COMPREPLY=( "$( compgen -W "$(_buildspec_test_names)" -- "${cur}" )" )
            ;;
      esac
      ;;

    cd)
      COMPREPLY=( "$( compgen  -W "$(_builder_names)" -- "${cur}" )" );;
    clean)
      local opts="-h --help -y --yes"
      COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
      ;;
    path)
      local opts="-b -be -e -h -o -s -t --buildscript --buildenv --errfile --help  --outfile --stagedir --testpath"
      COMPREPLY=( "$( compgen -W "$(_builder_names)" -- "${cur}" )" )
      if [[ $cur == -* ]] ; then
        COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
      fi
      ;;
    stats)
      COMPREPLY=( "$( compgen  -W "$(_test_name)" -- "${cur}" )" );;

    report|rt)
      local opts="--detailed --end --fail --filter --filterfields --format --formatfields --help --helpfilter --helpformat --latest --no-header --oldest --pager --pass --row-count --start --terse -d -e -f -h -n -p -s -t"
      local cmds="clear list path summary"
      local aliases="c ls p sm"
      COMPREPLY=( "$( compgen -W "${cmds} ${aliases}" -- "${cur}" )" )

      if [[ $cur == -* ]] ; then
        COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
      fi

      case "${prev}" in
        --filter)
            COMPREPLY=( "$( compgen -W "$(_avail_report_filterfields)" -- "${cur}" )" )
            ;;
        --format)
            COMPREPLY=( "$( compgen -W "$(_avail_report_formatfields)" -- "${cur}" )" )
            ;;
        summary|sm)
            local opts="-d -h --detailed --help"
            COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
            ;;
      esac
    ;;

    config|cg)

      local cmds="co compilers e edit ex executors p path profiles remove systems validate v view"
      local aliases="co e ex p v val"
      local opts="-h --help"

      COMPREPLY=( "$( compgen -W "${cmds} ${aliases}" -- "${cur}" )" )
      if [[ $cur == -* ]] ; then
        COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
      fi
      # handle completion logic for 'buildtest config <subcommand>' based on subcommands

      case "${COMP_WORDS[2+offset]}" in
        compilers|co)

          local opts="--help -h"
          local cmds="list find remove test"
          local aliases="rm"
          COMPREPLY=( "$( compgen -W "${cmds} ${aliases}" -- "${cur}" )" )
          if [[ $cur == -* ]] ; then
            COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
          fi

          case "${prev}" in
            list)
              local opts="--json --yaml -j -y"
              COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
              ;;
            find)
              local opts="--detailed --file --help --modulepath --update -d -h -m -u"
              COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
              ;;
            remove|rm)
              COMPREPLY=( "$( compgen -W "$(_avail_compilers)" -- "${cur}" )" )
              ;;
            test)
              COMPREPLY=( "$( compgen -W "$(_avail_compilers)" -- "${cur}" )" )
              ;;
          esac
          ;;
        executors|ex)
          local cmds="list ls rm remove"

          case ${COMP_WORDS[3+offset]} in
              list|ls)
                  local opts="--help --all --disabled --invalid --json --yaml -a -d -h -i -j -y"
                  COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
                  ;;
              rm|remove)
                  COMPREPLY=( "$( compgen -W "$(_all_executors)" -- "${cur}" )" )
                  ;;
              *)
                  COMPREPLY=( "$( compgen -W "${cmds}" -- "${cur}" )" )
                  ;;
          esac
          ;;
        validate|systems)
          local opts="-h --help"
          COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" );;
        view|v)
          local opts="--help --pager --theme -h"
          COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )

          case "${prev}" in --theme)
            COMPREPLY=( "$( compgen -W "$(_avail_color_themes)" -- "${cur}" )" )
            ;;
          esac
        ;;
        profiles|prof)
          local opts="--help -h"
          local cmds="list remove"
          local aliases="ls rm"
          COMPREPLY=( "$( compgen -W "${cmds} ${aliases}" -- "${cur}" )" )
          if [[ $cur == -* ]] ; then
            COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
          fi

          case "${prev}" in
            remove|rm)
              COMPREPLY=( "$( compgen -W "$(_avail_profiles)" -- "${cur}" )" )
              ;;
            list|ls)
              local opts="--json --theme --yaml -j -y"
              COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
              ;;
            --theme)
              COMPREPLY=( "$( compgen -W "$(_avail_color_themes)" -- "${cur}" )" )
              ;;
          esac
          ;;
        esac
      ;;
    inspect|it)
      local cmds="--help -h b buildspec ls list n name q query"
      COMPREPLY=( "$( compgen -W "${cmds}" -- "${cur}" )" )

      # case statement to handle completion for buildtest inspect [name|id|list] command
      case "${COMP_WORDS[2+offset]}" in
        list|ls)
          local opts="--builder --help --no-header --pager --row-count --terse -b -h -n"
          COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" );;
        name|n)
          COMPREPLY=( "$( compgen -W "$(_test_name)" -- "${cur}" )" )

          if [[ $cur == -* ]] ; then
            local opts="--help --pager -h"
            COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
          fi
          ;;
        buildspec|b)
          COMPREPLY=( "$( compgen -W "$(_test_buildspec)" -- "${cur}" )" )

          if [[ $cur == -* ]] ; then
            local opts="--all --help --pager -a -h"
            COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
          fi
          ;;
        query|q)
          COMPREPLY=( "$( compgen -W "$(_builder_names)" -- "${cur}" )" )
          if [[ $cur == -* ]] ; then
            local opts="--buildscript --buildenv --error --help --output --pager --testpath --theme -b -be -e -o -h -o -t"
            COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
          fi
          case "${prev}" in --theme)
            COMPREPLY=( "$( compgen -W "$(_avail_color_themes)" -- "${cur}" )" )
            return
          esac
          ;;
      esac
      ;;
    buildspec|bc)
      local cmds="edit-file edit-test find maintainers show show-fail summary validate"
      local aliases="ef et f m s sf sm val"
      local opts="-h --help"
      COMPREPLY=( "$( compgen -W "${cmds} ${aliases}" -- "${cur}" )" )

      if [[ $cur == -* ]] ; then
        COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
      fi

      # switch based on 2nd word 'buildtest buildspec <subcommand>'
      case ${COMP_WORDS[2+offset]} in
      find|f)
         case ${COMP_WORDS[3+offset]} in
         # completion for 'buildtest buildspec find invalid'
         invalid)
           local opts="--error --help --pager --row-count --terse -e -h"
           COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" );;
         # completion for rest of arguments
         *)
           local longopts="--buildspec --count --executors --filter --filterfields --format --formatfields --group-by-executor --group-by-tags --help --helpfilter --helpformat --no-header --pager --paths --quiet --rebuild --row-count --search --tags --terse"
           local shortopts="-b -d -e  -h -n -p -q -r -s -t"
           local cmds="invalid"

           COMPREPLY=( "$( compgen -W "${cmds} ${longopts} ${shortopts}" -- "${cur}" )" )

           case "${prev}" in
           --filter)
             COMPREPLY=( "$( compgen -W "$(_avail_buildspec_filterfields)" -- "${cur}" )" )
             ;;
           --format)
             COMPREPLY=( "$( compgen -W "$(_avail_buildspec_formatfields)" -- "${cur}" )" )
             ;;
           esac
           ;;
         esac
        ;;
      summary|sm)
         case ${COMP_WORDS[3+offset]} in
         # completion for rest of arguments
         *)
           local longopts="--help --pager"
           local shortopts="-h"
           local allopts="${longopts} ${shortopts}"
           COMPREPLY=( "$( compgen -W "${allopts}" -- "${cur}" )" );;
         esac
        ;;
      edit-file|ef)
        COMPREPLY=( "$( compgen -W "$(_avail_buildspecs)" -- "${cur}" )" );;
      edit-test|et)
        COMPREPLY=( "$( compgen -W "$(_buildspec_cache_test_names)" -- "${cur}" )" );;
      show|s)
        local opts="-h --help --theme"
        COMPREPLY=( "$( compgen -W "$(_buildspec_cache_test_names)" -- "${cur}" )" )
        if [[ $cur == -* ]] ; then
          COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
        fi

        case "${prev}" in --theme)
          COMPREPLY=( "$( compgen -W "$(_avail_color_themes)" -- "${cur}" )" )
          return
        esac
        ;;
      show-fail|sf)
        local opts="-h --help --theme"
        COMPREPLY=( "$( compgen -W "$(_failed_tests)" -- "${cur}" )" )
        if [[ $cur == -* ]] ; then
          COMPREPLY=( "$( compgen -W "$opts" -- "${cur}" )" )
        fi
        case "${prev}" in --theme)
          COMPREPLY=( "$( compgen -W "$(_avail_color_themes)" -- "${cur}" )" )
          return
        esac
        ;;
      maintainers|m)
        local opts="--breakdown --count  --help --no-header --pager  --row-count --terse  -b -c -h -n find"
        COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )

        case ${COMP_WORDS[3+offset]} in
        find)
          COMPREPLY=( "$( compgen -W "$(_avail_maintainers)" -- "${cur}" )" );;
        esac
        ;;
      validate|val)
        local opts="--buildspec --exclude --executor --name --tag -b -e -n -t -x "
        COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )

        case "${prev}" in
          -b|--buildspec|-x|--exclude)
              COMPREPLY=( "$( compgen -W "$(_avail_buildspecs)" -- "${cur}" )" )
              ;;
          -t|--tags)
              COMPREPLY=( "$( compgen -W "$(_avail_tags)" -- "${cur}" )" )
              ;;
          -e|--executor)
              COMPREPLY=( "$( compgen -W "$(_avail_executors)" -- "${cur}" )" )
              ;;
          -n|--name)
              COMPREPLY=( "$( compgen -W "$(_buildspec_test_names)" -- "${cur}" )" )
              ;;
        esac
      ;;
      esac
      ;;
    history|hy)
      local opts="--help -h"
      local cmds="list query"
      COMPREPLY=( "$( compgen -W "${cmds}" -- "${cur}" )" )
      if [[ $cur == -* ]] ; then
        COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
      fi

      case ${COMP_WORDS[2+offset]} in
      list)
        local opts="--help --no-header --pager --row-count --terse -h -n -t"
        COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
        ;;
      query)
        local opts="--help --log --output -h -l -o"
        COMPREPLY=( "$( compgen -W "$(_history_id)" -- "${cur}" )" )
        if [[ $cur == -* ]]; then
          COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
        fi
        ;;
      esac
      ;;
    cdash)
      local cmds="upload view"
      local opts="--help -h"

      COMPREPLY=( "$( compgen -W "${cmds}" -- "${cur}" )" )

      if [[ $cur == -* ]] ; then
        COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
      fi

      case "${prev}" in
        view)
            local opts="-h --help"
            COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
            ;;
        upload)
            local opts="--help --open --site -h -o"
            COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
            ;;
      esac
      ;;
    stylecheck|style)
      local opts="--help --no-black --no-isort --no-pyflakes --apply -a -h"
      COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
      ;;
    unittests|test)
      local opts="--coverage --help --pytestopts --sourcefiles -c -h -p -s"
      COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
      ;;
    show|s)
      COMPREPLY=( "$( compgen -W "$(_buildtest_show_commands)" -- "${cur}" )" )
      ;;
    commands|cmds)
      local opts="--help --with-aliases -a -h"
      COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
      ;;
    tutorial-examples)
      local cmds="aws spack"
      local opts="--help -h -d --dryrun --failfast -w --write"
      COMPREPLY=( "$( compgen -W "${cmds}" -- "${cur}" )" )
      if [[ $cur == -* ]] ; then
        COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
      fi
      ;;
    # options with only --help
    debugreport|info|docs)
      local opts="-h --help"
      COMPREPLY=( "$( compgen -W "${opts}" -- "${cur}" )" )
      ;;
    *)
      case "${cur}" in
      # print main options to buildtest
        -*)
          COMPREPLY=( "$( compgen -W "$(_buildtest_options)" -- "${cur}" )" );;

      # print main sub-commands to buildtest
        *)
          COMPREPLY=( "$( compgen -W "$(_buildtest_commands)" -- "${cur}" )" )
          case "${prev}" in
            --color)
                COMPREPLY=( "$( compgen -W "$(_supported_colors)" -- "${cur}" )" )
                ;;
            --loglevel|-l)
                COMPREPLY=( "$( compgen -W "DEBUG INFO WARNING ERROR CRITICAL" -- "${cur}" )" )
                ;;
            --editor)
                COMPREPLY=( "$( compgen -W "vi vim emacs nano" -- "${cur}" )" )
                ;;
          esac
          ;;
      esac
  esac
}

complete -o default -F _buildtest buildtest
