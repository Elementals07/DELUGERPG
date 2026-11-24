var webp_support=0;
$(function(){check_webp_feature(function(d){d&&(webp_support=1)});$(".npc_prof, #gymdisp .trainerbox > .imgwrap").click(function(){loadCss(csspref+"dex.css");var d=$(this).attr("href")||$(this).closest(".trainerbox").find("a.npc_prof").first().attr("href");d=d.slice(d.indexOf("npc/")+4);waitingDialog.show("Loading Trainer Team...");$.post("/ajax/npc/"+d+($("#tab_alola").length>0?"/gym":""),function(a){var c="";a.status=="nouser"?c='<div class="notify_error"> No Such Trainer. </div>':(c+='<div class="fright">',
c=a.trainid>=5E3?c+`<img style="height:80px;" src="${imageserver}images/trainers/${a.desc}${webp_support?".webp":".png"}"></div>`:c+`<img style="height:80px;" src="${imageserver}images/trainers/league/${toLower(a.trainer)}${webp_support?".webp":".png"}"></div>`,c+=`<h1 class="npcpoph1${a.trtype1?` typeclr-${toLower(a.trtype1)}`:""}">${a.trainer}</h1>`,a.trainid<5E3&&(c+=`<div id="npcinfobox" style="text-align: center;">
                                <h4 style="float:none;">${a.desc}${typeof a.badge!=="undefined"?` / ${a.badge}`:""}</h4>
                            </div><br>`),c+='<div id="npcbattlebuttons">',c=a.trainid<5E3?c+`<a class="btn btn-primary npcpopbattle" href="/battle/gym/${a.trainid}">Gym Battle</a>
                        <a class="btn btn-primary npcpopbattle" href="/battle/trainer/${a.trainid}">Trainer Battle</a>
                        <a class="btn btn-secondary npcpopbattle" href="/battle/trainer/${a.trainid}/inverse"><i class="fas fa-random"></i> Inverse Battle</a>`:c+`<a class="btn btn-primary npcpopbattle" href="/battle/trainer/${a.trainid}">Battle</a>
                        <a class="btn btn-secondary npcpopbattle" href="/battle/trainer/${a.trainid}/inverse"><i class="fas fa-random"></i> Inverse Battle</a>`,c+="</div>",a.randomstats&&(c+='<div class="notify_info mini" style="margin-top:10px;">Note: This trainer will have their pokemon\'s stats randomized during trainer battle.</div>'),a.elite4&&(c+='<div class="notify_info mini" style="margin-top:10px;">Note: After you beat all gyms and elite 4, this trainer will use lvl 100 pokemon.</div>'),
c+='<ul id="viewuteam">',$.each(a.teamm,function(){c+=`<li class="viewuteammember typeclr-${this.type1.toLowerCase()}">
                            <div class="name">
                                <img src="${this.img_loc}" alt="${this.name}" />
                                <br><h4>${this.name}</h4>
                            <br><i class="tbtn tbtn-${this.type1.toLowerCase()}"></i>
                            ${this.type2!=0?` <i class="tbtn tbtn-${this.type2.toLowerCase()}"></i>`:""}`;c+=`<br><span class="tle">Level:</span> ${this.level}
                            </div><div class="attk"><span class="t_bold">Moves</span>
                            <br>${this.attack1}
                            <br>${this.attack2}
                            <br>${this.attack3}
                            <br>${this.attack4}
                            </div></li>`}),c+="</ul><br />");waitingDialog.hide();Modal.show({head:a.trainer+"'s Profile",content:c})},"json").fail(function(){waitingDialog.hide();Modal.show({head:"Error",content:'<div class="notify_error">Error loading trainer team. Please try again.</div>'})});return!1});if($("#tab_standard").length>0){var e=["#tab_strong","#tab_ultimate","#tab_vip","#tab_standard"],b=window.location.hash;b!=""&&/^#[a-z0-9_]+$/.test(b)&&$("#tab_"+b.slice(1)).length||(b="#standard");
b=b.slice(1);e.remove("#tab_"+b);$(e.join(",")).hide(0);$(window).scrollTop(0);$("#t_"+b).addClass("glselect");$("#gymlinks").data("select",b);history.replaceState(null,"","#"+b)}else $("#tab_kanto").length>0&&(e="#tab_kanto #tab_johto #tab_hoenn #tab_sinnoh #tab_unova #tab_kalos #tab_alola #tab_galar #tab_paldea".split(" "),b=window.location.hash,b!=""&&/^#[a-z0-9_]+$/.test(b)&&$("#tab_"+b.slice(1)).length||(b="#kanto"),b=b.slice(1),e.remove("#tab_"+b),$(e.join(",")).hide(0),$(window).scrollTop(0),
$("#t_"+b).addClass("glselect"),$("#gymlinks").data("select",b),history.replaceState(null,"","#"+b));$("#gymlinks a").click(function(){var d=$(this).attr("id").slice(2),a=$("#gymlinks").data("select");if(d!=a)return $("#tab_"+a).hide(0),$("#tab_"+d).show(0),$("#t_"+a).removeClass("glselect"),$(this).addClass("glselect"),$("#gymlinks").data("select",d),history.replaceState(null,"","#"+d),!1})});
