var mobjs=0;
$(function(){function d(a,b){a.toggleClass("nav_open",b);a.children("a").first().attr("aria-expanded",b?"true":"false")}setTimeout(gen_tooltips,0);var e=!1;$(window).on("scroll.navaffix resize.navaffix",function(){var a=window.scrollY>=100;a!==e&&(e=a,$("#navwrap").toggleClass("affix",a),setTimeout(syncToastTop,50))});window.syncToastTop=function(){var a=$(".deluge-toast-wrapper.top");if(a.length){var b=document.getElementById("navwrap").getBoundingClientRect().bottom+4;if($("#navinf-dropdown:visible").length){var c=document.getElementById("navinf-dropdown").getBoundingClientRect().bottom+
10;c>b&&(b=c)}a.css("top",Math.round(b)+"px")}};$(document).on("keydown","#navid",function(a){if(a.key==="Escape"){var b=$(document.activeElement),c=b.closest("#navid > li");c.length&&(a.preventDefault(),b.is("#navid > li > a")?(d(c,!1),a=c.nextAll("li").first().children("a").first(),a.length&&a.focus()):c.children("a").first().focus())}});$(document).on("click","#navid > li > a",function(a){var b=$(this).parent("li");!b.children("ul").length||a.button!==0||a.ctrlKey||a.metaKey||a.shiftKey||(a.preventDefault(),
a=!b.hasClass("nav_open"),$("#navid > li.nav_open").each(function(){d($(this),!1)}),a&&d(b,!0))});$(document).on("click",function(a){$(a.target).closest("#navid").length||$("#navid > li.nav_open").each(function(){d($(this),!1)})});$(document).on("mouseenter focusin","#navid > li",function(){var a=$(this);$("#navid > li.nav_open").not(a).each(function(){d($(this),!1)})});$("#goingdown").length<=0&&($("#navinf").addClass("in").html(`<span id="userloggedin">
                <i class="fas fa-caret-down"></i>
                <img src="${n_avatar_25}" id="gravimg25" alt="" />
                <a href="/profile" role="button" aria-haspopup="true" aria-expanded="false">${$(window).width()>=1015?n_user:n_user.trunc(10)}</a>
            </span>`),typeof active_event!=="undefined"?(ndtop='<div id="ndtop"><a href="/event/">Active Event</a></div>',$("#navinf").addClass("aevent")):typeof active_event_code!=="undefined"?(ndtop=`<div id="ndtop"><a href="/event/info/${active_event_code}">Event Claim <i class="fas fa-gift"></i></a></div>`,$("#navinf").addClass("aevent")):ndtop="",$("#navinf-dropdown").html(ndtop+`<div id="ndleft">
                <img loading="lazy" id="nigrav" src="${n_avatar}" style="width:80px;height:80px;" alt="${n_user}'s avatar"/>
                <br><b>DelugeRPG Time (UTC)</b><br>${srvr_time}
                <div id="navtheme" class="btn-group" role="group"><a class="btn btn-dark btn-sm" href="/theme/dark"><i class="fad fa-moon"></i> Dark</a> <a class="btn btn-light btn-sm" href="/theme/light"><i class="fad fa-sun"></i> Light</a></div>
                <a href="/logout" title="logout" id="lnlogout" class="btn btn-danger" ${typeof rafftym!=="undefined"?'style="position:relative;top:-45px"':""}><i class="fas fa-power-off"></i> LOGOUT</a>
            </div>
            <div id="ndright">
                <div id="uname">${n_user}</div>
                <div id="ndcash"><b>Coins:</b> ${n_cash} <i class="fad fa-coins"></i></div>
                <hr style="width:65px;border:0;border-top:1px solid #999999;margin:5px auto;">
                <div id="linklist">
                    <a href="/profile">Profile</a>
                    <a href="/profile#preferences">Settings</a>
                    <a href="/lists">Friends and Blocklist</a>
                    <a href="/logs">Account Activity</a>
                    <a href="/terms">Privacy</a>
                    <a href="/intro">Help</a>
                </div>
                ${typeof ocount==="undefined"?"":`<small id="navcount" class="fright">${ocount} users online</small>`}
            </div>`));$("#navinf").click(function(a){if(!$("#goingdown").length)return(a=!$("#navinf-dropdown").is(":visible"))?($(this).addClass("antinav"),$("#navinf-dropdown").fadeIn(200,syncToastTop)):($(this).removeClass("antinav"),$("#navinf-dropdown").fadeOut(400,syncToastTop)),$("#userloggedin a").attr("aria-expanded",a?"true":"false"),!1});$(document).on("keydown","#navinf-dropdown",function(a){a.key==="Escape"&&(a.preventDefault(),$("#navinf").removeClass("antinav"),$("#userloggedin a").attr("aria-expanded",
"false"),$("#navinf-dropdown").fadeOut(400,syncToastTop),$("#userloggedin a").trigger("focus"))});$("html").click(function(a){$("#navinf-dropdown").is(":visible")&&$(a.target).parents().index($("#navinf-dropdown-wrapper"))==-1&&($("#navinf").removeClass("antinav"),$("#userloggedin a").attr("aria-expanded","false"),$("#navinf-dropdown").fadeOut(600,syncToastTop))})});
function gen_tooltips(){initTooltips($('[data-bs-toggle="tooltip"]'),{trigger:"hover click"});$('[data-bs-toggle="tooltip"]').off("mouseleave.gen_tt").on("mouseleave.gen_tt",function(){hideTooltips($(this))})};
